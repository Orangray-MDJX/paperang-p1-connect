/// zlib 兼容的 CRC32（IEEE 802.3 反射多项式，带种子）。
///
/// 与 Python `zlib.crc32(payload, seed)` 逐字节一致——协议帧校验依赖此语义。
library;

const int _poly = 0xEDB88320;

/// 顶层 final 惰性初始化，首次调用 crc32 时建表。
final List<int> _table = _buildTable();

List<int> _buildTable() {
  final table = List<int>.filled(256, 0);
  for (var n = 0; n < 256; n++) {
    var c = n;
    for (var k = 0; k < 8; k++) {
      c = (c & 1) != 0 ? (_poly ^ (c >>> 1)) : (c >>> 1);
    }
    table[n] = c;
  }
  return table;
}

int crc32(List<int> data, [int seed = 0]) {
  var c = seed ^ 0xFFFFFFFF;
  for (final b in data) {
    c = _table[(c ^ b) & 0xFF] ^ (c >>> 8);
  }
  return (c ^ 0xFFFFFFFF) & 0xFFFFFFFF;
}
