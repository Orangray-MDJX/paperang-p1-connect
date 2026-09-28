library;

import 'dart:typed_data';

/// RFCOMM 帧 → (dlci, ftype, credit, user)。user 不含 credit/FCS。
///
/// 长度字段不含可选 credit 字节与 FCS；若按长度切片前先去掉 credit，
/// 会静默丢掉应用层最后一字节（A5 的帧尾 0x5A）——对应测试验证这一点。
(int, int, int?, Uint8List?) parseRfcomm(Uint8List l2) {
  if (l2.length < 4) return (0, 0, null, null);
  final addr = l2[0], ctrl = l2[1], lb = l2[2];
  int length, off;
  if (lb & 1 != 0) {
    length = lb >> 1;
    off = 3;
  } else {
    length = (lb >> 1) | (l2[3] << 7);
    off = 4;
  }
  final dlci = addr >> 2;
  final ftype = ctrl & 0xEF;
  int? credit;
  Uint8List? user;
  if (ftype == 0xEF && dlci != 0) {
    if ((ctrl >> 4) & 1 != 0) {
      if (l2.length <= off) {
        throw const FormatException('truncated RFCOMM credit');
      }
      credit = l2[off];
      off += 1;
    }
    if (l2.length < off + length + 1) {
      throw const FormatException('truncated RFCOMM information/FCS');
    }
    user = Uint8List.fromList(l2.sublist(off, off + length));
  }
  return (dlci, ftype, credit, user);
}
