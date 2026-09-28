package dev.p1connect.paperang_p1

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.util.UUID

/**
 * mDNS/Bonjour 注册：_ipp._tcp + TXT（AirPrint 的 _universal 子类型在
 * NsdManager 上以 serviceType 变体尝试注册，失败不影响基础发现）。
 * 持有 MulticastLock，否则 WiFi 驱动会过滤多播。
 */
class MdnsBridge(private val context: Context, messenger: BinaryMessenger) {
    private val channel = MethodChannel(messenger, "p1/mdns")
    private var registration: NsdManager.RegistrationListener? = null
    private var multicastLock: WifiManager.MulticastLock? = null

    init {
        channel.setMethodCallHandler { call, result ->
            when (call.method) {
                "register" -> {
                    val name = call.argument<String>("name") ?: "Paperang P1"
                    val port = call.argument<Int>("port") ?: 8631
                    val txt = call.argument<Map<String, String>>("txt") ?: emptyMap()
                    register(name, port, txt, result)
                }
                "unregister" -> {
                    unregister()
                    result.success(null)
                }
                "uuid" -> result.success(stableUuid())
                else -> result.notImplemented()
            }
        }
    }

    private fun stableUuid(): String =
        UUID.nameUUIDFromBytes(
            (android.os.Build.MODEL + ".paperang-p1").toByteArray()
        ).toString()

    private fun register(
        name: String,
        port: Int,
        txt: Map<String, String>,
        result: MethodChannel.Result,
    ) {
        unregister()
        val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        acquireMulticastLock()
        val info = NsdServiceInfo().apply {
            serviceName = name
            serviceType = "_ipp._tcp."
            setPort(port)
            for ((k, v) in txt) {
                setAttribute(k, v)
            }
        }
        val listener = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(svc: NsdServiceInfo) {
                mainHandler.post { result.success(svc.serviceName) }
            }

            override fun onRegistrationFailed(svc: NsdServiceInfo, code: Int) {
                mainHandler.post {
                    result.error("register_failed", "NSD 注册失败 code=$code", null)
                }
            }

            override fun onUnregistrationFailed(svc: NsdServiceInfo, code: Int) {}
            override fun onServiceUnregistered(svc: NsdServiceInfo) {}
        }
        registration = listener
        try {
            nsd.registerService(info, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: Exception) {
            releaseMulticastLock()
            result.error("error", "${e.message}", null)
        }
    }

    fun unregister() {
        val nsd = context.getSystemService(Context.NSD_SERVICE) as? NsdManager
        try {
            registration?.let { nsd?.unregisterService(it) }
        } catch (_: Exception) {}
        registration = null
        releaseMulticastLock()
    }

    private fun acquireMulticastLock() {
        if (multicastLock != null) return
        val wifi = context.applicationContext
            .getSystemService(Context.WIFI_SERVICE) as? WifiManager ?: return
        multicastLock = wifi.createMulticastLock("p1-mdns").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseMulticastLock() {
        try { multicastLock?.release() } catch (_: Exception) {}
        multicastLock = null
    }

    private val mainHandler = android.os.Handler(android.os.Looper.getMainLooper())
}
