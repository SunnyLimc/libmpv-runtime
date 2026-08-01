package com.alexmercerind.media_kit_libs_android_video;

import androidx.annotation.NonNull;
import com.alexmercerind.mediakitandroidhelper.MediaKitAndroidHelper;
import io.flutter.embedding.engine.plugins.FlutterPlugin;

public final class MediaKitLibsAndroidVideoPlugin implements FlutterPlugin {
    static { System.loadLibrary("mpv"); }
    @Override
    public void onAttachedToEngine(@NonNull FlutterPluginBinding binding) {
        MediaKitAndroidHelper.setApplicationContextJava(binding.getApplicationContext());
    }
    @Override
    public void onDetachedFromEngine(@NonNull FlutterPluginBinding binding) {}
}
