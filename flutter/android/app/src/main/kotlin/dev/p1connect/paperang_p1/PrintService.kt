package dev.p1connect.paperang_p1

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder

/**
 * 前台服务：打印连接会话 + 局域网网关的常驻载体（connectedDevice 类型）。
 * 通知实时显示连接状态/电量/待打印数。状态更新走 update action 重投递。
 */
class PrintService : Service() {
    companion object {
        const val CHANNEL_ID = "p1_status"
        const val NOTIFICATION_ID = 1

        fun start(context: Context) {
            val intent = Intent(context, PrintService::class.java)
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, PrintService::class.java))
        }

        /** 更新通知；服务未运行时先拉起（拉起即进入前台）。 */
        fun update(context: Context, state: String, battery: String, pending: Int) {
            val intent = Intent(context, PrintService::class.java)
                .setAction(ACTION_UPDATE)
                .putExtra("state", state)
                .putExtra("battery", battery)
                .putExtra("pending", pending)
            try {
                context.startForegroundService(intent)
            } catch (_: Exception) {
                // App 在后台且服务未运行时可能被系统拒绝，忽略本次更新
            }
        }

        private const val ACTION_UPDATE = "dev.p1connect.paperang_p1.UPDATE"
        private const val ACTION_STOP = "dev.p1connect.paperang_p1.STOP"
    }

    private var stateText = "正在连接打印机"
    private var batteryText = ""
    private var pendingCount = 0

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_UPDATE -> {
                stateText = intent.getStringExtra("state") ?: stateText
                batteryText = intent.getStringExtra("battery") ?: batteryText
                pendingCount = intent.getIntExtra("pending", pendingCount)
            }
        }
        val notification = buildNotification()
        if (Build.VERSION.SDK_INT >= 30) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        return START_STICKY
    }

    private fun createChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "打印服务状态",
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = "打印机连接状态与任务进度"
            setShowBadge(false)
        }
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val contentIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this, 1,
            Intent(this, PrintService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val text = buildString {
            append(stateText)
            if (batteryText.isNotEmpty()) append(" · ").append(batteryText)
        }
        val builder = if (Build.VERSION.SDK_INT >= 26) {
            Notification.Builder(this, CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION") Notification.Builder(this)
        }
        return builder
            .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
            .setContentTitle("Paperang P1")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(contentIntent)
            .setNumber(pendingCount)
            .addAction(
                android.R.drawable.ic_menu_close_clear_cancel,
                "停止",
                stopIntent,
            )
            .build()
    }
}
