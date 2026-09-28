package dev.p1connect.paperang_p1

import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context

import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import java.io.IOException
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger

/**
 * 经典蓝牙 RFCOMM 通道（SPP）。单活动连接；数据/断连经 EventChannel 回传。
 * 读线程按 64KB 块读取，EOF 视为对端主动断开（对应桌面版 EOF 语义）。
 */
class BluetoothBridge(private val context: Context, messenger: BinaryMessenger) {
    companion object {
        private const val TAG = "P1Bluetooth"
        private val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
    }

    private val method = MethodChannel(messenger, "p1/bluetooth")
    private val events = EventChannel(messenger, "p1/bluetooth/events")
    private var sink: EventChannel.EventSink? = null
    private var socket: BluetoothSocket? = null
    private var readThread: Thread? = null
    private val generation = AtomicInteger(0)

    init {
        method.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "isSupported" -> result.success(adapter() != null)
                    "isEnabled" -> result.success(adapter()?.isEnabled == true)
                    "listBonded" -> {
                        val names = ArrayList<Map<String, String>>()
                        adapter()?.bondedDevices?.forEach { d ->
                            names.add(
                                mapOf("address" to d.address, "name" to (d.name ?: ""))
                            )
                        }
                        result.success(names)
                    }
                    "connect" -> {
                        val address = call.argument<String>("address")
                        if (address == null) {
                            result.error("bad_args", "address required", null)
                        } else {
                            connect(address, result)
                        }
                    }
                    "write" -> {
                        val data = call.argument<ByteArray>("data")
                        val s = socket
                        if (s == null || data == null) {
                            result.error("not_open", "bluetooth not connected", null)
                        } else {
                            try {
                                s.outputStream.write(data)
                                s.outputStream.flush()
                                result.success(null)
                            } catch (e: IOException) {
                                onDisconnected(generation.get(), "蓝牙写入失败: ${e.message}")
                                result.error("io", "${e.message}", null)
                            }
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
            } catch (e: Exception) {
                result.error("error", "${e.message}", null)
            }
        }
        events.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(args: Any?, ev: EventChannel.EventSink?) {
                sink = ev
            }
            override fun onCancel(args: Any?) {
                sink = null
            }
        })
    }

    private fun adapter(): BluetoothAdapter? {
        val bm = context.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        return bm?.adapter
    }

    private fun connect(address: String, result: MethodChannel.Result) {
        val adapter = adapter()
        if (adapter == null || !adapter.isEnabled) {
            result.error("adapter", "蓝牙未开启", null)
            return
        }
        close()
        val device = try {
            adapter.getRemoteDevice(address)
        } catch (e: IllegalArgumentException) {
            result.error("bad_address", "无效的蓝牙地址", null)
            return
        }
        val gen = generation.incrementAndGet()
        val s = device.createRfcommSocketToServiceRecord(SPP_UUID)
        Thread {
            try {
                adapter.cancelDiscovery()
                s.connect()
                socket = s
                readLoop(s, gen)
                mainHandler.post { result.success(null) }
            } catch (e: IOException) {
                try { s.close() } catch (_: IOException) {}
                val msg = "蓝牙连接失败: ${e.message}"
                onDisconnected(gen, msg)
                mainHandler.post { result.error("connect_failed", msg, null) }
            } catch (e: SecurityException) {
                try { s.close() } catch (_: IOException) {}
                mainHandler.post {
                    result.error("permission", "缺少蓝牙权限（BLUETOOTH_CONNECT）", null)
                }
            }
        }.also { readThread = it }.start()
    }

    private fun readLoop(s: BluetoothSocket, gen: Int) {
        val buf = ByteArray(65536)
        try {
            while (gen == generation.get() && s.isConnected) {
                val n = s.inputStream.read(buf)
                if (n < 0) {
                    onDisconnected(gen, "RFCOMM 对端关闭连接 (EOF)")
                    return
                }
                if (n > 0) {
                    val chunk = buf.copyOf(n)
                    mainHandler.post {
                        if (gen == generation.get()) {
                            sink?.success(mapOf("type" to "data", "data" to chunk))
                        }
                    }
                }
            }
        } catch (e: IOException) {
            if (gen == generation.get()) {
                onDisconnected(gen, "RFCOMM 读取失败: ${e.message}")
            }
        }
    }

    private fun onDisconnected(gen: Int, reason: String) {
        mainHandler.post {
            if (gen == generation.get()) {
                Log.i(TAG, "disconnected: $reason")
                sink?.success(mapOf("type" to "disconnected", "reason" to reason))
            }
        }
    }

    fun close() {
        generation.incrementAndGet()
        try { socket?.close() } catch (_: IOException) {}
        socket = null
    }

    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
}
