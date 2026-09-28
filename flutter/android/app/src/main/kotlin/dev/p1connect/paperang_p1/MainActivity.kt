package dev.p1connect.paperang_p1

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileOutputStream

class MainActivity : FlutterActivity() {
    companion object {
        private const val PICK_REQUEST = 7101
        private const val ACTION_SHARED_LAUNCH = "dev.p1connect.paperang_p1.SHARED_LAUNCH"
    }

    private var bluetooth: BluetoothBridge? = null
    private var usb: UsbBridge? = null
    private var mdns: MdnsBridge? = null
    private var pendingShare: String? = null
    private var pickResult: MethodChannel.Result? = null
    private var requestPermissionLauncher: MethodChannel.Result? = null

    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        intent?.takeIf { it.action == Intent.ACTION_SEND }?.let { handleShare(it) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.action == Intent.ACTION_SEND) handleShare(intent)
    }

    /** 把分享/选中的图片复制到缓存文件（content URI 不能跨进程长期持有）。 */
    private fun cacheUri(uri: Uri, prefix: String): String? = try {
        val out = File(cacheDir, "$prefix-${System.currentTimeMillis()}.img")
        contentResolver.openInputStream(uri)?.use { input ->
            FileOutputStream(out).use { output -> input.copyTo(output) }
        } ?: return null
        out.absolutePath
    } catch (e: Exception) {
        null
    }

    private fun handleShare(intent: Intent) {
        @Suppress("DEPRECATION")
        val uri = if (Build.VERSION.SDK_INT >= 33) {
            intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
        } else {
            intent.getParcelableExtra(Intent.EXTRA_STREAM)
        } as? Uri ?: return
        cacheUri(uri, "shared")?.let { pendingShare = it }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        bluetooth = BluetoothBridge(this, messenger)
        usb = UsbBridge(this, messenger)
        mdns = MdnsBridge(this, messenger)

        MethodChannel(messenger, "p1/service").setMethodCallHandler { call, result ->
            when (call.method) {
                "start" -> { PrintService.start(this); result.success(null) }
                "stop" -> { PrintService.stop(this); result.success(null) }
                "update" -> PrintService.update(
                    this,
                    call.argument<String>("state") ?: "",
                    call.argument<String>("battery") ?: "",
                    call.argument<Int>("pending") ?: 0,
                ).also { result.success(null) }
                else -> result.notImplemented()
            }
        }

        MethodChannel(messenger, "p1/intent").setMethodCallHandler { call, result ->
            when (call.method) {
                "filesDir" -> result.success(filesDir.absolutePath)
                "requestNotifications" -> requestNotifications(result)
                "takeSharedImage" -> {
                    val p = pendingShare
                    pendingShare = null
                    result.success(p)
                }
                "setBootStart" -> {
                    val enabled = call.argument<Boolean>("enabled") ?: false
                    getSharedPreferences("p1", Context.MODE_PRIVATE)
                        .edit().putBoolean("boot_start", enabled).apply()
                    result.success(null)
                }
                "pickImage" -> {
                    pickResult = result
                    val pick = Intent(Intent.ACTION_GET_CONTENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "image/*"
                    }
                    @Suppress("DEPRECATION")
                    startActivityForResult(
                        Intent.createChooser(pick, "选择图片"), PICK_REQUEST,
                    )
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun requestNotifications(result: MethodChannel.Result) {
        if (Build.VERSION.SDK_INT < 33) {
            result.success(true)
            return
        }
        if (checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            result.success(true)
            return
        }
        requestPermissionLauncher = result
        @Suppress("DEPRECATION")
        requestPermissions(
            arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 7102,
        )
    }

    @Deprecated("Deprecated in Java")
    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 7102) return
        val r = requestPermissionLauncher
        requestPermissionLauncher = null
        r?.success(
            grantResults.isNotEmpty() &&
                grantResults[0] == android.content.pm.PackageManager.PERMISSION_GRANTED,
        )
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != PICK_REQUEST) return
        val r = pickResult
        pickResult = null
        if (r == null) return
        if (resultCode != Activity.RESULT_OK || data?.data == null) {
            r.success(null)
            return
        }
        r.success(cacheUri(data.data!!, "picked"))
    }

    override fun onDestroy() {
        bluetooth?.close()
        usb?.close()
        mdns?.unregister()
        super.onDestroy()
    }
}

/** 快捷磁贴：点击即连接打印机（拉起 App 并请求连接）。 */
class PrintTileService : TileService() {
    override fun onStartListening() {
        super.onStartListening()
        qsTile?.state = Tile.STATE_INACTIVE
        qsTile?.updateTile()
    }

    override fun onClick() {
        super.onClick()
        startActivityAndCollapse(
            Intent(this, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                action = "dev.p1connect.paperang_p1.CONNECT"
            },
        )
    }
}

/** 开机自启（设置项开启后生效）：只拉起前台服务，连接由服务/App 自行恢复。 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = context.getSharedPreferences("p1", Context.MODE_PRIVATE)
        if (!prefs.getBoolean("boot_start", false)) return
        PrintService.start(context)
    }
}
