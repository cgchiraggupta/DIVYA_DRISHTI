package com.divyadrishti.app;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * Small config handoff from the WebView (which knows the Supabase URL/anon
 * key from .env, and the pairing code once paired) to native services that
 * run outside the WebView's lifecycle -- WakeListenerService and
 * VoiceCaptureService cannot read import.meta.env, so WakeConfigPlugin
 * writes here once at app start / after pairing, and the services read it
 * when a background event fires.
 */
final class DivyaPrefs {
    private static final String FILE = "divyadrishti_wake_config";

    private DivyaPrefs() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    static void save(Context context, String pairingCode, String supabaseUrl,
                      String supabaseAnonKey, String sarvamApiKey, String localDeviceHost) {
        prefs(context).edit()
            .putString("pairing_code", pairingCode)
            .putString("supabase_url", supabaseUrl)
            .putString("supabase_anon_key", supabaseAnonKey)
            .putString("sarvam_api_key", sarvamApiKey)
            .putString("local_device_host", localDeviceHost)
            .apply();
    }

    static String pairingCode(Context context) {
        return prefs(context).getString("pairing_code", "");
    }

    static String supabaseUrl(Context context) {
        return prefs(context).getString("supabase_url", "");
    }

    static String supabaseAnonKey(Context context) {
        return prefs(context).getString("supabase_anon_key", "");
    }

    static String sarvamApiKey(Context context) {
        return prefs(context).getString("sarvam_api_key", "");
    }

    static String localDeviceHost(Context context) {
        return prefs(context).getString("local_device_host", "");
    }

    static boolean isConfigured(Context context) {
        return !pairingCode(context).isEmpty() && !supabaseUrl(context).isEmpty();
    }
}
