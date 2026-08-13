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

/** Starts and stops the foreground service that keeps guidance alive in a pocket. */
@CapacitorPlugin(
    name = "BackgroundGuardian",
    permissions = {
        @Permission(alias = BackgroundGuardianPlugin.NOTIFICATIONS, strings = { Manifest.permission.POST_NOTIFICATIONS })
    }
)
public class BackgroundGuardianPlugin extends Plugin {
    static final String NOTIFICATIONS = "notifications";

    private static boolean running = false;

    @PluginMethod
    public void start(PluginCall call) {
        // Android 13+ hides the ongoing notification without this, and a
        // foreground service with no visible notification is a poor trade.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
            && getPermissionState(NOTIFICATIONS) != PermissionState.GRANTED) {
            requestPermissionForAlias(NOTIFICATIONS, call, "afterNotificationPermission");
            return;
        }
        launch(call);
    }

    @PermissionCallback
    private void afterNotificationPermission(PluginCall call) {
        launch(call);
    }

    private void launch(PluginCall call) {
        Intent intent = new Intent(getContext(), GuardianService.class);
        try {
            getContext().startForegroundService(intent);
            running = true;
        } catch (Exception error) {
            call.reject("Could not start background guidance: " + error.getMessage());
            return;
        }
        JSObject result = new JSObject();
        result.put("running", true);
        call.resolve(result);
    }

    @PluginMethod
    public void stop(PluginCall call) {
        getContext().stopService(new Intent(getContext(), GuardianService.class));
        running = false;
        JSObject result = new JSObject();
        result.put("running", false);
        call.resolve(result);
    }

    @PluginMethod
    public void isRunning(PluginCall call) {
        JSObject result = new JSObject();
        result.put("running", running);
        call.resolve(result);
    }
}
