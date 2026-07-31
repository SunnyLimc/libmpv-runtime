import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';

void main() {
  MediaKit.ensureInitialized();
  runApp(const RuntimeConsumerApp());
}

class RuntimeConsumerApp extends StatelessWidget {
  const RuntimeConsumerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(home: Scaffold(body: Text('libmpv-runtime consumer')));
  }
}
