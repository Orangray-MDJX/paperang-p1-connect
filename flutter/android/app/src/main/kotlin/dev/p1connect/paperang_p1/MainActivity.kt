package dev.p1connect.paperang_p1

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var bluetooth: BluetoothBridge? = null
    private var usb: UsbBridge? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        bluetooth = BluetoothBridge(this, messenger)
        usb = UsbBridge(this, messenger)
        MethodChannel(messenger, "p1/service").setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> {
                    PrintService.start(this)
                    result.success(null)
                }
                "stop" -> {
                    PrintService.stop(this)
                    result.success(null)
                }
                "update" -> PrintService.update(
                    this,
                    call.argument<String>("state") ?: "",
                    call.argument<String>("battery") ?: "",
                    call.argument<Int>("pending") ?: 0,
                ).also { result.success(null) }
                else -> result.notImplemented()
            }
        }
    }

    override fun onDestroy() {
        bluetooth?.close()
        usb?.close()
        super.onDestroy()
    }
}
