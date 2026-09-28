import 'package:flutter/material.dart';

void main() {
  // F3/F4 将替换为完整 MD3 界面；当前占位以保持工程可构建。
  runApp(const PaperangApp());
}

class PaperangApp extends StatelessWidget {
  const PaperangApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Paperang P1',
      theme: ThemeData(
        useMaterial3: true,
        colorSchemeSeed: const Color(0xFF252A33),
      ),
      home: const Scaffold(body: Center(child: Text('Paperang P1 Connect'))),
    );
  }
}
