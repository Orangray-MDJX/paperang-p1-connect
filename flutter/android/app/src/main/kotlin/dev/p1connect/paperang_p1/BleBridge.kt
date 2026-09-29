package dev.p1connect.paperang_p1

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattDescriptor
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.content.Context
import android.os.Build
import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import java.util.UUID
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * BLE GATT 传输（FF00 profile，直译桌面 transport_ble.py）：
 * - 服务 0000ff00-...（备选 Nordic-UART 49535343-...）
 * - 写特征 FF02（按 GATT 属性探测已知变体），通知 FF01/FF03
 * - 无需系统配对；DUAL 设备用经典地址直连 GATT。
 */
@SuppressLint("MissingPermission")
class BleBridge(private val context: Context, messenger: BinaryMessenger) {
    companion object {
        private const val TAG = "P1Ble"
        private val SERVICE_UUIDS = listOf(
            "0000ff00-0000-1000-8000-00805f9b34fb",
            "49535343-fe7d-4ae5-8fa9-9fafd205e455",
        )
        private val KNOWN_WRITE_CHARS = listOf(
            "0000ff02-0000-1000-8000-00805f9b34fb",
            "49535343-6daa-4d02-abf6-19569aca69fe",
            "49535343-8841-43f4-a8d4-ecbe34729bb3",
        )
        private val KNOWN_NOTIFY_CHARS = listOf(
            "0000ff01-0000-1000-8000-00805f9b34fb",
            "0000ff03-0000-1000-8000-00805f9b34fb",
            "49535343-1e4d-4bd9-ba61-23c647249616",
        )
        private val NAME_PREFIXES = listOf("paperang", "miaomiaoji")
        private val CCC_DESCRIPTOR: UUID =
            UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")
        private const val CONNECT_TIMEOUT_S = 15L
        private const val SERVICE_TIMEOUT_S = 8L
    }

    private val method = MethodChannel(messenger, "p1/ble")
    private val events = EventChannel(messenger, "p1/ble/events")
    private var sink: EventChannel.EventSink? = null
    private var gatt: BluetoothGatt? = null
    private var writeChar: BluetoothGattCharacteristic? = null
    private val writeQueue = ConcurrentLinkedQueue<ByteArray>()
    @Volatile private var writeInFlight = false

    init {
        method.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "connect" -> {
                        val address = call.argument<String>("address")
                        if (address == null) {
                            result.error("bad_args", "address required", null)
                        } else {
                            Thread { connect(address, result) }.start()
                        }
                    }
                    "write" -> {
                        val data = call.argument<ByteArray>("data")
                        val wc = writeChar
                        val g = gatt
                        if (data == null) {
                            result.error("bad_args", "data required", null)
                        } else if (wc == null || g == null) {
                            result.error("not_open", "ble not connected", null)
                        } else {
                            writeQueue.add(data)
                            pumpWrites()
                            result.success(null)
                        }
                    }
                    "close" -> {
                        close()
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            } catch (e: SecurityException) {
                result.error("permission", "缺少蓝牙权限（BLUETOOTH_CONNECT）", null)
            }
        }
        events.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(args: Any?, ev: EventChannel.EventSink?) { sink = ev }
            override fun onCancel(args: Any?) { sink = null }
        })
    }

    private fun adapter(): BluetoothAdapter? {
        val bm = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        return bm?.adapter
    }

    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())

    private fun emit(map: Map<String, Any?>) {
        mainHandler.post { sink?.success(map) }
    }

    private fun connect(address: String, result: MethodChannel.Result) {
        val adapter = adapter()
        if (adapter == null || !adapter.isEnabled) {
            mainHandler.post { result.error("adapter", "蓝牙未开启", null) }
            return
        }
        close()
        // P1 的 LE 地址可能与经典地址不同且不总在广播：先扫描（按名字/服务
        // UUID 匹配）拿真实 LE 设备，扫不到再按传入地址直连。
        Thread { scanThenConnect(adapter, address, result) }.start()
    }

    private fun scanThenConnect(
        adapter: BluetoothAdapter, address: String, result: MethodChannel.Result,
    ) {
        val found = CountDownLatch(1)
        val target = java.util.concurrent.atomic.AtomicReference<BluetoothDevice?>(null)
        var scanner: android.bluetooth.le.BluetoothLeScanner? = null
        try {
            scanner = adapter.bluetoothLeScanner
        } catch (_: SecurityException) {
        }
        if (scanner != null) {
            val callback = object : android.bluetooth.le.ScanCallback() {
                override fun onScanResult(callbackType: Int, r: android.bluetooth.le.ScanResult) {
                    val dev = r.device ?: return
                    val name = try { dev.name } catch (_: SecurityException) { null }
                    val svc = r.scanRecord?.serviceUuids ?: listOf<android.os.ParcelUuid>()
                    val svcBlob = svc.joinToString(" ") { it.uuid.toString().lowercase() }
                    val hit = (name != null && NAME_PREFIXES.any { name.lowercase().startsWith(it) }) ||
                        ("ff00" in svcBlob || "49535343" in svcBlob)
                    if (hit) {
                        target.set(dev)
                        Log.i(TAG, "scan hit ${dev.address} name=$name")
                        found.countDown()
                    }
                }
            }
            try {
                scanner.startScan(callback)
                found.await(10, TimeUnit.SECONDS)
            } catch (e: SecurityException) {
                Log.w(TAG, "scan needs permission: ${e.message}")
            } finally {
                try { scanner.stopScan(callback) } catch (_: Exception) {}
            }
        }
        val scanned = target.get()
        val device = scanned ?: adapter.getRemoteDevice(address)
        if (scanned == null) {
            Log.w(TAG, "scan miss, falling back to $address")
        }
        gattConnect(device, result)
    }

    private fun gattConnect(device: BluetoothDevice, result: MethodChannel.Result) {
        val connected = CountDownLatch(1)
        val servicesDone = CountDownLatch(1)
        val failure = java.util.concurrent.atomic.AtomicReference<String?>(null)

        val callback = object : BluetoothGattCallback() {
            override fun onConnectionStateChange(
                g: BluetoothGatt, status: Int, newState: Int,
            ) {
                when (newState) {
                    BluetoothProfile.STATE_CONNECTED -> {
                        Log.i(TAG, "gatt connected, discovering services")
                        g.discoverServices()
                    }
                    BluetoothProfile.STATE_DISCONNECTED -> {
                        Log.w(TAG, "gatt disconnected status=$status")
                        if (status != BluetoothGatt.GATT_SUCCESS) {
                            failure.set("BLE 连接断开 status=$status")
                        }
                        connected.countDown()
                        servicesDone.countDown()
                        writeChar = null
                        emit(mapOf("type" to "disconnected", "reason" to (failure.get() ?: "closed")))
                    }
                }
            }

            override fun onServicesDiscovered(g: BluetoothGatt, status: Int) {
                connected.countDown()
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    failure.set("服务发现失败 status=$status")
                    servicesDone.countDown()
                    return
                }
                // MTU 请求 517（FF02 单写最大 512-3；A5 块 480 需要大 MTU）
                g.requestMtu(517)
            }

            override fun onMtuChanged(g: BluetoothGatt, mtu: Int, status: Int) {
                Log.i(TAG, "mtu=$mtu status=$status")
                val detected = detectCharacteristics(g)
                if (detected) {
                    val notifyChar = pickNotify(g)
                    if (notifyChar != null) {
                        val ok = g.setCharacteristicNotification(notifyChar, true)
                        val d = notifyChar.getDescriptor(CCC_DESCRIPTOR)
                        if (d != null) {
                            if (Build.VERSION.SDK_INT >= 33) {
                                g.writeDescriptor(d, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE)
                            } else {
                                @Suppress("DEPRECATION")
                                d.value = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
                                @Suppress("DEPRECATION")
                                g.writeDescriptor(d)
                            }
                        }
                        Log.i(TAG, "notify=${notifyChar.uuid} set=$ok")
                    }
                } else {
                    failure.set("BLE 服务特征不完整（FF00/写/通知缺失）")
                }
                servicesDone.countDown()
            }

            override fun onCharacteristicChanged(
                g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, value: ByteArray,
            ) {
                emit(mapOf("type" to "data", "data" to value))
            }

            @Deprecated("pre-33 signature")
            @Suppress("DEPRECATION")
            override fun onCharacteristicChanged(
                g: BluetoothGatt, characteristic: BluetoothGattCharacteristic,
            ) {
                if (Build.VERSION.SDK_INT < 33) {
                    @Suppress("DEPRECATION")
                    val v = characteristic.value ?: return
                    emit(mapOf("type" to "data", "data" to v))
                }
            }

            override fun onCharacteristicWrite(
                g: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int,
            ) {
                writeInFlight = false
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    Log.e(TAG, "characteristic write status=$status")
                }
                pumpWrites()
            }
        }

        val g = device.connectGatt(context, false, callback, BluetoothDevice.TRANSPORT_LE)
        if (g == null) {
            mainHandler.post { result.error("connect_failed", "connectGatt 返回 null", null) }
            return
        }
        gatt = g
        try {
            if (!connected.await(CONNECT_TIMEOUT_S, TimeUnit.SECONDS)) {
                failure.set("BLE 连接超时")
            }
            if (failure == null && !servicesDone.await(SERVICE_TIMEOUT_S, TimeUnit.SECONDS)) {
                failure.set("BLE 服务发现超时")
            }
        } catch (_: InterruptedException) {
            failure.set("BLE 连接中断")
        }
        val err = failure.get()
        if (err != null || writeChar == null) {
            val msg = err ?: "BLE 特征未就绪"
            Log.e(TAG, "connect failed: $msg")
            close()
            emit(mapOf("type" to "disconnected", "reason" to msg))
            mainHandler.post { result.error("connect_failed", msg, null) }
        } else {
            Log.i(TAG, "connected, write=${writeChar!!.uuid}")
            mainHandler.post { result.success(null) }
        }
    }

    private fun detectCharacteristics(g: BluetoothGatt): Boolean {
        val chars = mutableListOf<BluetoothGattCharacteristic>()
        for (svc in g.services) {
            if (svc.uuid.toString().lowercase() in SERVICE_UUIDS) {
                chars.addAll(svc.characteristics)
            }
        }
        if (chars.isEmpty()) {
            for (uid in KNOWN_WRITE_CHARS + KNOWN_NOTIFY_CHARS) {
                g.getService(UUID.fromString(uid))?.let { svc ->
                    for (c in svc.characteristics) {
                        if (c.uuid.toString().lowercase() == uid) chars.add(c)
                    }
                }
            }
        }
        val wc = pickWrite(chars)
        writeChar = wc
        Log.i(TAG, "detected write=${wc?.uuid} from ${chars.size} candidates")
        return wc != null
    }

    private fun pickWrite(
        chars: List<BluetoothGattCharacteristic>,
    ): BluetoothGattCharacteristic? {
        for (uid in KNOWN_WRITE_CHARS) {
            for (c in chars) {
                val props = c.properties
                val canWrite = (props and BluetoothGattCharacteristic.PROPERTY_WRITE) != 0 ||
                    (props and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0
                if (c.uuid.toString().lowercase() == uid && canWrite) return c
            }
        }
        for (c in chars) {
            val props = c.properties
            if ((props and BluetoothGattCharacteristic.PROPERTY_WRITE) != 0 ||
                (props and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0
            ) {
                return c
            }
        }
        return null
    }

    private fun pickNotify(g: BluetoothGatt): BluetoothGattCharacteristic? {
        for (uid in KNOWN_NOTIFY_CHARS) {
            for (svc in g.services) {
                for (c in svc.characteristics) {
                    if (c.uuid.toString().lowercase() == uid &&
                        (c.properties and BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0
                    ) {
                        return c
                    }
                }
            }
        }
        for (svc in g.services) {
            if (svc.uuid.toString().lowercase() !in SERVICE_UUIDS) continue
            for (c in svc.characteristics) {
                if ((c.properties and BluetoothGattCharacteristic.PROPERTY_NOTIFY) != 0) {
                    return c
                }
            }
        }
        return null
    }

    @Synchronized
    private fun pumpWrites() {
        if (writeInFlight) return
        val g = gatt ?: return
        val wc = writeChar ?: return
        val data = writeQueue.poll() ?: return
        if (Build.VERSION.SDK_INT >= 33) {
            val ret = g.writeCharacteristic(
                wc, data,
                if ((wc.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0)
                    BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                else BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT,
            )
            writeInFlight = ret == android.bluetooth.BluetoothStatusCodes.SUCCESS
        } else {
            @Suppress("DEPRECATION")
            wc.value = data
            @Suppress("DEPRECATION")
            wc.writeType =
                if ((wc.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) != 0)
                    BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
                else BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            @Suppress("DEPRECATION")
            writeInFlight = g.writeCharacteristic(wc)
        }
        if (!writeInFlight) {
            // 写未受理：丢弃并在下轮重试剩余队列，避免卡死
            Log.e(TAG, "writeCharacteristic rejected")
        }
    }

    fun close() {
        writeQueue.clear()
        writeInFlight = false
        val g = gatt
        gatt = null
        writeChar = null
        if (g != null) {
            try { g.disconnect() } catch (_: Exception) {}
            try { g.close() } catch (_: Exception) {}
        }
    }
}
