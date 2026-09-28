package dev.p1connect.paperang_p1

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

/**
 * USB 打印机通道：UsbManager 权限流程 + interface 0 的 bulk IN/OUT 端点。
 * 对应桌面版 usbprint.sys 通道（VID 0x4348 / PID 0x5584）。
 */
class UsbBridge(private val context: Context, messenger: BinaryMessenger) {
    companion object {
        private const val TAG = "P1Usb"
        private const val ACTION_PERMISSION = "dev.p1connect.paperang_p1.USB_PERMISSION"
    }

    private val method = MethodChannel(messenger, "p1/usb")
    private val events = EventChannel(messenger, "p1/usb/events")
    private var sink: EventChannel.EventSink? = null
    private var connection: UsbDeviceConnection? = null
    private var iface: UsbInterface? = null
    private var epOut: UsbEndpoint? = null
    private var epIn: UsbEndpoint? = null
    private var readThread: Thread? = null
    @Volatile private var running = false
    private var pendingPermission: MethodChannel.Result? = null

    private val usbManager: UsbManager
        get() = context.getSystemService(Context.USB_SERVICE) as UsbManager

    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())

    init {
        method.setMethodCallHandler { call, result ->
            when (call.method) {
                "listDevices" -> {
                    val vid = call.argument<Int>("vid")
                    val pid = call.argument<Int>("pid")
                    val out = ArrayList<Map<String, Any>>()
                    usbManager.deviceList.values.forEach { d ->
                        if ((vid == null || d.vendorId == vid) &&
                            (pid == null || d.productId == pid)
                        ) {
                            out.add(
                                mapOf(
                                    "vid" to d.vendorId,
                                    "pid" to d.productId,
                                    "name" to (d.productName ?: ""),
                                    "hasPermission" to usbManager.hasPermission(d),
                                )
                            )
                        }
                    }
                    result.success(out)
                }
                "open" -> {
                    val vid = call.argument<Int>("vid") ?: -1
                    val pid = call.argument<Int>("pid") ?: -1
                    open(vid, pid, result)
                }
                "write" -> {
                    val data = call.argument<ByteArray>("data")
                    val conn = connection
                    val ep = epOut
                    if (conn == null || ep == null || data == null) {
                        result.error("not_open", "usb not open", null)
                    } else {
                        var offset = 0
                        while (offset < data.size) {
                            val n = conn.bulkTransfer(ep, data, offset, data.size - offset, 5000)
                            if (n < 0) {
                                onDisconnected("USB 写入失败")
                                result.error("io", "bulkTransfer OUT 失败", null)
                                return@setMethodCallHandler
                            }
                            offset += n
                        }
                        result.success(null)
                    }
                }
                "close" -> {
                    close()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
        events.setStreamHandler(object : EventChannel.StreamHandler {
            override fun onListen(args: Any?, ev: EventChannel.EventSink?) { sink = ev }
            override fun onCancel(args: Any?) { sink = null }
        })
        registerPermissionReceiver()
    }

    private fun registerPermissionReceiver() {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                if (intent?.action == ACTION_PERMISSION) {
                    val granted =
                        intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                    val r = pendingPermission
                    pendingPermission = null
                    if (granted) {
                        val vid = intent.getIntExtra("vid", -1)
                        val pid = intent.getIntExtra("pid", -1)
                        if (r != null) open(vid, pid, r)
                    } else {
                        r?.error("permission", "用户拒绝了 USB 权限", null)
                    }
                }
            }
        }
        val filter = IntentFilter(ACTION_PERMISSION)
        if (Build.VERSION.SDK_INT >= 33) {
            // API 33+ 必须显式声明非导出（系统安全要求）
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            context.registerReceiver(receiver, filter)
        }
    }

    private fun findDevice(vid: Int, pid: Int): UsbDevice? =
        usbManager.deviceList.values.firstOrNull {
            it.vendorId == vid && it.productId == pid
        }

    private fun open(vid: Int, pid: Int, result: MethodChannel.Result) {
        val device = findDevice(vid, pid)
        if (device == null) {
            result.error("no_device", "未找到 USB 设备 vid=$vid pid=$pid", null)
            return
        }
        if (!usbManager.hasPermission(device)) {
            pendingPermission = result
            val flags = if (Build.VERSION.SDK_INT >= 31)
                PendingIntent.FLAG_MUTABLE else 0
            val intent = Intent(ACTION_PERMISSION).setPackage(context.packageName)
            intent.putExtra("vid", vid)
            intent.putExtra("pid", pid)
            usbManager.requestPermission(device, PendingIntent.getBroadcast(context, 0, intent, flags))
            return
        }
        try {
            close()
            val conn = usbManager.openDevice(device)
            if (conn == null) {
                result.error("open_failed", "openDevice 返回 null", null)
                return
            }
            val face = device.getInterface(0)
            if (!conn.claimInterface(face, true)) {
                conn.close()
                result.error("claim_failed", "claimInterface 失败", null)
                return
            }
            var out: UsbEndpoint? = null
            var inp: UsbEndpoint? = null
            for (i in 0 until face.endpointCount) {
                val ep = face.getEndpoint(i)
                if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK) {
                    if (ep.direction == UsbConstants.USB_DIR_OUT) out = ep else inp = ep
                }
            }
            if (out == null || inp == null) {
                conn.close()
                result.error("no_endpoints", "未找到 bulk IN/OUT 端点", null)
                return
            }
            connection = conn
            iface = face
            epOut = out
            epIn = inp
            running = true
            readThread = Thread { readLoop(conn, inp) }.also { it.start() }
            Log.i(TAG, "usb open vid=$vid pid=$pid")
            result.success(null)
        } catch (e: Exception) {
            result.error("error", "${e.message}", null)
        }
    }

    private fun readLoop(conn: UsbDeviceConnection, ep: UsbEndpoint) {
        val buf = ByteArray(65536)
        while (running) {
            val n = conn.bulkTransfer(ep, buf, buf.size, 250)
            if (n > 0) {
                val chunk = buf.copyOf(n)
                mainHandler.post {
                    if (running) sink?.success(mapOf("type" to "data", "data" to chunk))
                }
            } else if (n < 0) {
                // 持续错误视为断开（超时 -1 与错误无法区分时保守忽略短超时）
                onDisconnected("USB 读取失败")
                return
            }
        }
    }

    private fun onDisconnected(reason: String) {
        mainHandler.post {
            Log.i(TAG, "disconnected: $reason")
            sink?.success(mapOf("type" to "disconnected", "reason" to reason))
        }
    }

    fun close() {
        running = false
        try { iface?.let { connection?.releaseInterface(it) } } catch (_: Exception) {}
        try { connection?.close() } catch (_: Exception) {}
        connection = null
        iface = null
        epIn = null
        epOut = null
    }}
