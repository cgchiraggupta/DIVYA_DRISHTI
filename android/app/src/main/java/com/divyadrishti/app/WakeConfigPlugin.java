package com.divyadrishti.app;

import android.Manifest;
import android.content.Intent;
import android.os.Build;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/**
 * Bridges JS -> native for background wake-and-listen: hands the WebView's
 * config (pairing code, Supabase URL/anon key, Sarvam key, resolved glasses
 * host) to DivyaPrefs so WakeListenerService and VoiceCaptureService can run
 * with the phone locked and the app not in the foreground, then starts/stops
 * the always-on (network-only, no mic) wake listener.
 */
@CapacitorPlugin(
    name = "WakeConfig",
    permissions = {
        @Permission(alias = WakeConfigPlugin.MIC, strings = { Manifest.permission.RECORD_AUDIO }),
        @Permission(alias = WakeConfigPlugin.NOTIFICATIONS, strings = { Manifest.permission.POST_NOTIFICATIONS })
    }
)
public class WakeConfigPlugin extends Plugin {
    static final String MIC = "mic";
    static final String NOTIFICATIONS = "notifications";

    @PluginMethod
    public void sync(PluginCall call) {
        String pairingCode = call.getString("pairingCode", "");
        String supabaseUrl = call.getString("supabaseUrl", "");
        String supabaseAnonKey = call.getString("supabaseAnonKey", "");
        String sarvamApiKey = call.getString("sarvamApiKey", "");
        String localDeviceHost = call.getString("localDeviceHost", "");

        DivyaPrefs.save(getContext(), pairingCode, supabaseUrl, supabaseAnonKey, sarvamApiKey, localDeviceHost);
        call.resolve();
    }

    /** Request RECORD_AUDIO + (Android 13+) POST_NOTIFICATIONS before the
     * background listener can ever promote itself to a mic-type foreground
     * service -- both must be granted up front, not discovered mid-wake. */
    @PluginMethod
    public void requestPermissions(PluginCall call) {
        if (getPermissionState(MIC) != PermissionState.GRANTED) {
            requestPermissionForAlias(MIC, call, "afterMicPermission");
            return;
        }
        afterMicPermission(call);
    }

    @PermissionCallback
    private void afterMicPermission(PluginCall call) {
        if (getPermissionState(MIC) != PermissionState.GRANTED) {
            reportPermissions(call);
            return;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && getPermissionState(NOTIFICATIONS) != PermissionState.GRANTED) {
            requestPermissionForAlias(NOTIFICATIONS, call, "afterNotificationPermission");
            return;
        }
        reportPermissions(call);
    }

    @PermissionCallback
    private void afterNotificationPermission(PluginCall call) {
        reportPermissions(call);
    }

    @PluginMethod
    public void checkPermissions(PluginCall call) {
        reportPermissions(call);
    }

    private void reportPermissions(PluginCall call) {
        JSObject result = new JSObject();
        result.put("mic", getPermissionState(MIC) == PermissionState.GRANTED);
        result.put(
            "notifications",
            Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU
                || getPermissionState(NOTIFICATIONS) == PermissionState.GRANTED
        );
        call.resolve(result);
    }

    /** Starts the always-on (no mic yet) listener that watches for the
     * glasses button's wake command and only then promotes to a
     * microphone-type foreground service -- see WakeListenerService. */
    @PluginMethod
    public void startWakeListening(PluginCall call) {
        if (!DivyaPrefs.isConfigured(getContext())) {
            call.reject("Call sync() with pairing/Supabase config first.");
            return;
        }
        if (getPermissionState(MIC) != PermissionState.GRANTED) {
            call.reject("Microphone permission is required for wake-and-listen.");
            return;
        }
        try {
            getContext().startForegroundService(new Intent(getContext(), WakeListenerService.class));
        } catch (Exception error) {
            call.reject("Could not start wake listener: " + error.getMessage());
            return;
        }
        JSObject result = new JSObject();
        result.put("running", true);
        call.resolve(result);
    }

    @PluginMethod
    public void stopWakeListening(PluginCall call) {
        getContext().stopService(new Intent(getContext(), WakeListenerService.class));
        getContext().stopService(new Intent(getContext(), VoiceCaptureService.class));
        JSObject result = new JSObject();
        result.put("running", false);
        call.resolve(result);
    }

    @PluginMethod
    public void isWakeListening(PluginCall call) {
        JSObject result = new JSObject();
        result.put("running", WakeListenerService.isRunning());
        call.resolve(result);
    }
}
