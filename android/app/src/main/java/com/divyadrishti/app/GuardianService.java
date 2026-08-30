package com.divyadrishti.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

/**
 * Keeps the glasses link alive while the phone is pocketed.
 *
 * Guidance is useless if it stops the moment the screen turns off, but Android
 * suspends the CPU and parks the Wi-Fi radio for a backgrounded app. A
 * foreground service plus a partial wake lock and a Wi-Fi lock keeps the
 * one-second poll and the spoken alerts running during a walk.
 */
public class GuardianService extends Service {
    private static final String CHANNEL_ID = "divyadrishti_guardian";
    private static final int NOTIFICATION_ID = 4201;
    /** Safety valve so a crashed page can never hold the CPU awake all day. */
    private static final long WAKE_LOCK_TIMEOUT_MS = 4L * 60L * 60L * 1000L;

    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Reverted 2026-08-31: adding FOREGROUND_SERVICE_TYPE_MICROPHONE here
        // crash-looped the app on targetSdk 36 -- Android additionally requires
        // an "eligible state" (active recording / recently foregrounded) at the
        // exact startForeground() call, which this always-on pairing-time
        // service never has. Background mic access needs a different approach.
        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
            ? ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            : 0;
        ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(), type);
        acquireLocks();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        releaseLocks();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(CHANNEL_ID) != null) return;
        NotificationChannel channel = new NotificationChannel(
            CHANNEL_ID,
            "Obstacle guidance",
            NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Keeps obstacle alerts running while walking.");
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    private Notification buildNotification() {
        Intent launch = new Intent(this, MainActivity.class);
        launch.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT
            | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent pending = PendingIntent.getActivity(this, 0, launch, flags);

        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Divya Drishti is guiding you")
            .setContentText("Obstacle alerts stay on with the screen off.")
            .setSmallIcon(android.R.drawable.ic_menu_compass)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setContentIntent(pending)
            .build();
    }

    private void acquireLocks() {
        PowerManager power = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (power != null && (wakeLock == null || !wakeLock.isHeld())) {
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DivyaDrishti::Guardian");
            wakeLock.setReferenceCounted(false);
            wakeLock.acquire(WAKE_LOCK_TIMEOUT_MS);
        }

        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (wifi != null && (wifiLock == null || !wifiLock.isHeld())) {
            int mode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
            wifiLock = wifi.createWifiLock(mode, "DivyaDrishti::GuardianWifi");
            wifiLock.setReferenceCounted(false);
            wifiLock.acquire();
        }
    }

    private void releaseLocks() {
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        wakeLock = null;
        wifiLock = null;
    }
}
