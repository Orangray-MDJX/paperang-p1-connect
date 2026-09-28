/// 最小异步互斥锁：保护设备命令串行与打印/保活互斥（对应 asyncio.Lock）。
library;

class AsyncLock {
  Future<void> _tail = Future.value();

  Future<T> synchronize<T>(Future<T> Function() action) {
    final run = _tail.then((_) => action());
    // 无论成功失败都推进队尾，错误由调用方处理。
    _tail = run.then((_) {}, onError: (_) {});
    return run;
  }
}
