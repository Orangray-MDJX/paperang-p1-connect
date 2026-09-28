/// P1 打印坐标系的共享常量（对应 Python 版 paperang_p1/__init__.py）。
library;

const int lineDots = 384; // 有效打印宽度（点）
const int lineBytes = 48; // 每行字节数（384/8，MSB 在前，1=黑）
const int deviceDpi = 203; // 设备自报 DPI（打印坐标）
const String appVersion = '0.2.0';
