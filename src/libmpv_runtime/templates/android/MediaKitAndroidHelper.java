package com.alexmercerind.mediakitandroidhelper;

import android.content.Context;
import android.net.Uri;
import androidx.annotation.Keep;

@Keep
public final class MediaKitAndroidHelper {
    static { System.loadLibrary("mediakitandroidhelper"); }
    private static Context applicationContext;
    public static native long newGlobalObjectRef(Object value);
    public static native void deleteGlobalObjectRef(long reference);
    public static native String copyAssetToFilesDir(String assetName);
    private static native void setApplicationContextNative(Context context);
    public static void setApplicationContextJava(Context context) {
        applicationContext = context;
        setApplicationContextNative(context);
    }
    public static native int openFileDescriptorNative(String uri);
    public static int openFileDescriptorJava(String uri) {
        try {
            return applicationContext.getContentResolver()
                .openFileDescriptor(Uri.parse(uri), "r").detachFd();
        } catch (Throwable error) {
            return -1;
        }
    }
    private MediaKitAndroidHelper() {}
}
