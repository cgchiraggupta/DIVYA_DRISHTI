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
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

import org.json.JSONObject;

import java.net.URI;
import java.util.concurrent.atomic.AtomicBoolean;

import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

/**
 * Watches for the glasses' physical button "wake" command even when the app
 * is fully backgrounded or the screen is locked, so the user never has to
 * open the phone -- press the button, the mic opens.
 *
 * This service itself never touches the microphone (foregroundServiceType
 * "connectedDevice", same as GuardianService) -- it only holds a WebSocket to
 * the Pi's local link, same protocol as localSocketLink.js. The moment a
 * wake_requested message arrives, it starts VoiceCaptureService, which is
 * the one that promotes to a microphone-type foreground service, and only
 * at the instant recording actually begins -- Android requires that
 * "eligible state" exactly when startForeground(..., TYPE_MICROPHONE) is
 * called (see VoiceCaptureService and the removed attempt in
 * GuardianService's history for why this can't be combined into one
 * always-mic-type service).
 *
 * Reconnects with backoff like localSocketLink.js; runs independently of
 * the WebView so it survives the WebView being suspended in the background.
 */
public class WakeListenerService extends Service {
    private static final String CHANNEL_ID = "divyadrishti_wake_listener";
    private static final int NOTIFICATION_ID = 4202;
    private static final long WAKE_LOCK_TIMEOUT_MS = 12L * 60L * 60L * 1000L;
    private static final int WS_PORT = 8766;
    private static final long[] RECONNECT_DELAYS_MS = { 1_000, 2_000, 4_000, 8_000, 15_000, 30_000 };

    static final String ACTION_STOP = "com.divyadrishti.app.action.STOP_WAKE_LISTENER";

    private static final AtomicBoolean running = new AtomicBoolean(false);

    private PowerManager.WakeLock wakeLock;
    private WifiManager.WifiLock wifiLock;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private WebSocketClient wsClient;
    private int reconnectAttempt = 0;
    private boolean stopping = false;

    static boolean isRunning() {
        return running.get();
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }

        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
            ? ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            : 0;
        ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(), type);
        running.set(true);
        acquireLocks();
        stopping = false;
        connect();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        stopping = true;
        running.set(false);
        handler.removeCallbacksAndMessages(null);
        closeSocket();
        releaseLocks();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void connect() {
        if (stopping) return;
        String host = DivyaPrefs.localDeviceHost(this);
        String pairingCode = DivyaPrefs.pairingCode(this);
        if (host.isEmpty() || pairingCode.isEmpty()) {
            scheduleReconnect();
            return;
        }

        // closeSocket() (below) never blocks the caller -- this whole method
        // runs on the main-thread Handler, and a blocking close here (the
        // original bug: closeBlocking() on this thread) could hang the UI
        // thread waiting on a network socket, which is what an ANR looks
        // like from the outside ("app freezes / auto-closes").
        closeSocket();
        try {
            URI uri = new URI("ws://" + host + ":" + WS_PORT + "/v1/stream?code=" + pairingCode);
            WebSocketClient client = new WebSocketClient(uri) {
                @Override
                public void onOpen(ServerHandshake handshake) {
                    reconnectAttempt = 0;
                }

                @Override
                public void onMessage(String message) {
                    handleMessage(message);
                }

                @Override
                public void onClose(int code, String reason, boolean remote) {
                    if (wsClient == this && !stopping) scheduleReconnect();
                }

                @Override
                public void onError(Exception ex) {
                    // onClose follows; reconnect handled there.
                }
            };
            wsClient = client;
            // connect() (non-blocking) hands off to the library's own I/O
            // thread; connectBlocking() would repeat the same main-thread
            // stall this fix removes.
            client.connect();
        } catch (Exception error) {
            scheduleReconnect();
        }
    }

    private void handleMessage(String raw) {
        try {
            JSONObject message = new JSONObject(raw);
            if ("wake_requested".equals(message.optString("type"))) {
                Intent capture = new Intent(this, VoiceCaptureService.class);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    startForegroundService(capture);
                } else {
                    startService(capture);
                }
            }
        } catch (Exception ignored) {
            // Malformed/unrelated frame -- nothing to act on.
        }
    }

    private void closeSocket() {
        if (wsClient != null) {
            try {
                // close(), not closeBlocking() -- this method runs on the
                // main-thread Handler; blocking here to wait for the close
                // handshake is what caused the app to freeze/ANR while
                // reconnect attempts piled up against an unreachable host.
                wsClient.close();
            } catch (Exception ignored) {
                // best-effort
            }
            wsClient = null;
        }
    }

    private void scheduleReconnect() {
        if (stopping) return;
        int index = Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1);
        long delay = RECONNECT_DELAYS_MS[index];
        reconnectAttempt += 1;
        handler.postDelayed(this::connect, delay);
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(CHANNEL_ID) != null) return;
        NotificationChannel channel = new NotificationChannel(
            CHANNEL_ID,
            "Voice wake listener",
            NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("Watches for the glasses button so you can start talking without opening the phone.");
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    private Notification buildNotification() {
        Intent launch = new Intent(this, MainActivity.class);
        launch.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT
            | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent contentIntent = PendingIntent.getActivity(this, 0, launch, flags);

        Intent stopIntent = new Intent(this, WakeListenerService.class).setAction(ACTION_STOP);
        PendingIntent stopPending = PendingIntent.getService(this, 0, stopIntent, flags);

        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Ready for the glasses button")
            .setContentText("Press the button on your glasses, then start talking.")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setContentIntent(contentIntent)
            .addAction(0, "Stop", stopPending)
            .build();
    }

    private void acquireLocks() {
        PowerManager power = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (power != null && (wakeLock == null || !wakeLock.isHeld())) {
            wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "DivyaDrishti::WakeListener");
            wakeLock.setReferenceCounted(false);
            wakeLock.acquire(WAKE_LOCK_TIMEOUT_MS);
        }
        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (wifi != null && (wifiLock == null || !wifiLock.isHeld())) {
            int mode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
            wifiLock = wifi.createWifiLock(mode, "DivyaDrishti::WakeListenerWifi");
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
