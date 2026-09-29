package dev.p1connect.paperang_p1

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.Environment
import android.os.ParcelFileDescriptor
import android.provider.MediaStore
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream

/**
 * PDF 能力：系统 PdfRenderer 的平台通道封装。
 * - open(data|path) → {pageCount}
 * - renderPage(index, width) → PNG 字节（矢量缩放到目标宽度，白底）
 * - close() 释放
 * - saveImageToDownloads(png, name) → 保存导出图
 */
class PdfBridge(private val context: Context, messenger: BinaryMessenger) {
    private val channel = MethodChannel(messenger, "p1/pdf")
    private var renderer: PdfRenderer? = null
    private var fd: ParcelFileDescriptor? = null
    private var file: File? = null

    init {
        channel.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "open" -> {
                        val data = call.argument<ByteArray>("data")
                        if (data == null) {
                            result.error("bad_args", "data required", null)
                            return@setMethodCallHandler
                        }
                        val f = File(context.cacheDir, "pdf-${System.currentTimeMillis()}.pdf")
                        FileOutputStream(f).use { it.write(data) }
                        result.success(openFile(f))
                    }
                    "openPath" -> {
                        val path = call.argument<String>("path")
                        if (path == null) {
                            result.error("bad_args", "path required", null)
                            return@setMethodCallHandler
                        }
                        result.success(openFile(File(path)))
                    }
                    "renderPage" -> {
                        val index = call.argument<Int>("index") ?: 0
                        val width = call.argument<Int>("width") ?: 768
                        val r = renderer
                            ?: throw IllegalStateException("PDF not opened")
                        if (index < 0 || index >= r.pageCount) {
                            throw IllegalArgumentException("page index out of range")
                        }
                        r.openPage(index).use { page ->
                            val scale = width.toFloat() / page.width
                            val h = (page.height * scale).toInt().coerceAtLeast(1)
                            val bmp = Bitmap.createBitmap(
                                width.coerceAtLeast(1), h,
                                Bitmap.Config.ARGB_8888,
                            )
                            bmp.eraseColor(-1) // 白底：透明 PDF 区域按纸面处理
                            val transform = Matrix().apply { setScale(scale, scale) }
                            page.render(bmp, null, transform, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                            val out = ByteArrayOutputStream()
                            bmp.compress(Bitmap.CompressFormat.PNG, 100, out)
                            bmp.recycle()
                            result.success(out.toByteArray())
                        }
                    }
                    "close" -> {
                        close()
                        result.success(null)
                    }
                    "saveImageToDownloads" -> {
                        val data = call.argument<ByteArray>("data")
                        val name = call.argument<String>("name") ?: "page.png"
                        if (data == null) {
                            result.error("bad_args", "data required", null)
                            return@setMethodCallHandler
                        }
                        result.success(saveToDownloads(data, name))
                    }
                    else -> result.notImplemented()
                }
            } catch (e: SecurityException) {
                result.error("security", "${e.message}", null)
            } catch (e: Exception) {
                result.error("error", "${e.message}", null)
            }
        }
    }

    private fun openFile(f: File): Map<String, Any> {
        close()
        if (!f.exists() || f.length() == 0L) {
            throw IllegalArgumentException("PDF 文件不存在或为空")
        }
        fd = ParcelFileDescriptor.open(
            f, ParcelFileDescriptor.MODE_READ_ONLY,
        )
        renderer = PdfRenderer(requireNotNull(fd))
        file = f
        return mapOf(
            "pageCount" to renderer!!.pageCount,
            "path" to f.absolutePath,
        )
    }

    private fun saveToDownloads(png: ByteArray, name: String): String {
        val safeName = if (name.endsWith(".png")) name else "$name.png"
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, safeName)
            put(MediaStore.Downloads.MIME_TYPE, "image/png")
            if (Build.VERSION.SDK_INT >= 29) {
                put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                put(MediaStore.Downloads.IS_PENDING, 1)
            } else {
                @Suppress("DEPRECATION")
                put(
                    MediaStore.Images.Media.DATA,
                    File(
                        Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                        safeName,
                    ).absolutePath,
                )
            }
        }
        val resolver = context.contentResolver
        val collection = if (Build.VERSION.SDK_INT >= 29) {
            MediaStore.Downloads.EXTERNAL_CONTENT_URI
        } else {
            @Suppress("DEPRECATION")
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        }
        val uri = resolver.insert(collection, values)
            ?: throw IllegalStateException("MediaStore insert 失败")
        resolver.openOutputStream(uri)?.use { it.write(png) }
            ?: throw IllegalStateException("打开输出流失败")
        if (Build.VERSION.SDK_INT >= 29) {
            resolver.update(
                uri,
                ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) },
                null, null,
            )
        }
        return uri.toString()
    }

    fun close() {
        try { renderer?.close() } catch (_: Exception) {}
        try { fd?.close() } catch (_: Exception) {}
        renderer = null
        fd = null
        file?.delete()
        file = null
    }
}
