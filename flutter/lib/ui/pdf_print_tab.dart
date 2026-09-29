import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../services/app_controller.dart';
import '../services/pdf_service.dart';
import 'controller_scope.dart';

/// PDF 打印页：选择 → 逐页预览（翻页/缩放）→ 全部/当前页打印、当前页保存。
class PdfPrintTab extends StatefulWidget {
  const PdfPrintTab({super.key});

  @override
  State<PdfPrintTab> createState() => _PdfPrintTabState();
}

class _PdfPrintTabState extends State<PdfPrintTab> {
  String? _path;
  int? _pageCount;
  int _index = 0;
  final Map<int, Uint8List> _cache = {};
  bool _busy = false;
  String? _error;
  int? _density;
  final _controller = PageController();

  @override
  void dispose() {
    _controller.dispose();
    PdfService.close();
    super.dispose();
  }

  Future<void> _pick() async {
    setState(() => _busy = true);
    try {
      final path = await PdfService.pickPdf();
      if (path == null) return;
      final pages = await PdfService.openPath(path);
      if (!mounted) return;
      setState(() {
        _path = path;
        _pageCount = pages;
        _index = 0;
        _cache.clear();
        _error = null;
      });
      _controller.jumpToPage(0);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<Uint8List> _page(int i) async {
    if (_path == null) throw const PdfException('未打开 PDF');
    if (_cache.containsKey(i)) return _cache[i]!;
    final png = await PdfService.renderPage(i, width: 768);
    _cache[i] = png;
    return png;
  }

  Future<void> _submit(AppController c, {required bool currentOnly}) async {
    if (_busy || _pageCount == null) return;
    setState(() => _busy = true);
    try {
      // 打印页统一按 384 点重渲染（预览是 768，不能直接复用）
      final pages = <Uint8List>[];
      final range = currentOnly
          ? [_index]
          : List.generate(_pageCount!, (i) => i);
      for (final i in range) {
        pages.add(await PdfService.renderPage(i, width: 384));
      }
      final title = _path!.split('/').last;
      final id = await c.submitPdfPages(pages, title, density: _density);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('任务 $id 已提交（${pages.length} 页）')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _saveCurrent() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final png = await PdfService.renderPage(_index, width: 1536);
      final name =
          '${_path!.split('/').last.replaceAll('.pdf', '')}-p${_index + 1}';
      await PdfService.saveToDownloads(png, name);
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('已保存到下载目录：$name.png')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = ControllerScope.of(context);
    if (_pageCount == null) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.picture_as_pdf, size: 64),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _busy ? null : _pick,
              icon: const Icon(Icons.folder_open),
              label: const Text('选择 PDF'),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
          ],
        ),
      );
    }
    return Column(
      children: [
        Expanded(
          child: PageView.builder(
            controller: _controller,
            itemCount: _pageCount,
            onPageChanged: (i) => setState(() => _index = i),
            itemBuilder: (context, i) => InteractiveViewer(
              maxScale: 6,
              child: Center(
                child: FutureBuilder<Uint8List>(
                  future: _page(i),
                  builder: (context, snap) => snap.hasData
                      ? Image.memory(snap.data!)
                      : snap.hasError
                      ? Text(
                          '${snap.error}',
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        )
                      : const CircularProgressIndicator(),
                ),
              ),
            ),
          ),
        ),
        SafeArea(
          top: false,
          child: Column(
            children: [
              Text('第 ${_index + 1}/$_pageCount 页 · 双指缩放'),
              OverflowBar(
                alignment: MainAxisAlignment.center,
                spacing: 8,
                children: [
                  TextButton.icon(
                    onPressed: _busy ? null : _pick,
                    icon: const Icon(Icons.folder_open),
                    label: const Text('换文件'),
                  ),
                  TextButton.icon(
                    onPressed: _busy ? null : _saveCurrent,
                    icon: const Icon(Icons.download),
                    label: const Text('保存本页'),
                  ),
                ],
              ),
              OverflowBar(
                alignment: MainAxisAlignment.center,
                spacing: 8,
                children: [
                  OutlinedButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _submit(c, currentOnly: true),
                    icon: const Icon(Icons.filter_1),
                    label: const Text('打印本页'),
                  ),
                  FilledButton.icon(
                    onPressed: _busy
                        ? null
                        : () => _submit(c, currentOnly: false),
                    icon: const Icon(Icons.print),
                    label: const Text('打印全部'),
                  ),
                  PopupMenuButton<int?>(
                    initialValue: _density,
                    onSelected: (v) => setState(() => _density = v),
                    itemBuilder: (_) => [
                      const PopupMenuItem(value: null, child: Text('浓度：跟随全局')),
                      for (final v in [30, 50, 80, 100])
                        PopupMenuItem(value: v, child: Text('浓度 $v')),
                    ],
                    child: const Padding(
                      padding: EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 8,
                      ),
                      child: Icon(Icons.tune),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}
