package com.divyadrishti.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;

import androidx.core.app.NotificationCompat;
import androidx.core.app.ServiceCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Runs one wake-triggered voice turn entirely natively, so it works with the
 * app fully closed and the phone locked: promotes to a microphone-type
 * foreground service at the exact moment recording starts (the "eligible
 * state" Android requires -- see the reverted attempt noted in
 * GuardianService's history, which failed because it tried to hold
 * TYPE_MICROPHONE continuously instead of only while actually recording),
 * captures speech via the on-device SpeechRecognizer, auto-stops after
 * SILENCE_TIMEOUT_MS of silence, sends the transcript to the divya-chat
 * Supabase Edge Function (same contract as services/divyaChat.js), speaks
 * the reply with Android's built-in TextToSpeech, then stops itself --
 * dropping back to WakeListenerService's no-mic idle state until the next
 * button press.
 */
public class VoiceCaptureService extends Service {
    private static final String CHANNEL_ID = "divyadrishti_voice_capture";
    private static final int NOTIFICATION_ID = 4203;
    private static final long SILENCE_TIMEOUT_MS = 5_000L;
    private static final String LISTEN_LOCALE = "hi-IN";

    private final Handler handler = new Handler(Looper.getMainLooper());
    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private Runnable silenceTimeout;
    private boolean finished = false;

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Promote to a mic-type foreground service right here, right before
        // actually starting to record -- this is the "actively recording"
        // eligible state Android checks at this exact call.
        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
            ? ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            : 0;
        ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification("Listening…"), type);
        startListening();
        return START_NOT_STICKY;
    }

    @Override
    public void onDestroy() {
        finished = true;
        handler.removeCallbacksAndMessages(null);
        if (recognizer != null) {
            recognizer.destroy();
            recognizer = null;
        }
        if (tts != null) {
            tts.stop();
            tts.shutdown();
            tts = null;
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void startListening() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            finishWithSpeech("आवाज़ पहचान अभी उपलब्ध नहीं है।");
            return;
        }

        recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        recognizer.setRecognitionListener(new RecognitionListener() {
            @Override public void onReadyForSpeech(Bundle params) {}

            @Override
            public void onBeginningOfSpeech() {
                cancelSilenceTimeout();
            }

            @Override public void onRmsChanged(float rmsdB) {}
            @Override public void onBufferReceived(byte[] buffer) {}

            @Override
            public void onEndOfSpeech() {
                updateNotification("Thinking…");
            }

            @Override
            public void onError(int error) {
                if (finished) return;
                // SpeechRecognizer's own timeouts (no speech / speech timeout)
                // land here, not onEndOfSpeech -- treat both the same as our
                // silence auto-stop: just end the turn quietly.
                if (error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
                    || error == SpeechRecognizer.ERROR_NO_MATCH) {
                    finishSilently();
                } else if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) {
                    finishWithSpeech("माइक की अनुमति नहीं है।");
                } else {
                    finishSilently();
                }
            }

            @Override
            public void onResults(Bundle results) {
                cancelSilenceTimeout();
                List<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                String heard = (matches == null || matches.isEmpty()) ? "" : matches.get(0);
                if (heard == null || heard.trim().isEmpty()) {
                    finishSilently();
                    return;
                }
                handleTranscript(heard.trim());
            }

            @Override public void onPartialResults(Bundle partialResults) {}
            @Override public void onEvent(int eventType, Bundle params) {}
        });

        Intent recognizerIntent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        recognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        recognizerIntent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, LISTEN_LOCALE);
        recognizerIntent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        recognizerIntent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, SILENCE_TIMEOUT_MS);
        recognizerIntent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, SILENCE_TIMEOUT_MS);

        recognizer.startListening(recognizerIntent);

        // Backstop in case the recognizer never calls onBeginningOfSpeech at
        // all (no speech from the moment the mic opens) -- the OS-level
        // silence extras above cover "spoke, then went quiet", this covers
        // "never spoke".
        silenceTimeout = this::finishSilently;
        handler.postDelayed(silenceTimeout, SILENCE_TIMEOUT_MS);
    }

    private void cancelSilenceTimeout() {
        if (silenceTimeout != null) {
            handler.removeCallbacks(silenceTimeout);
            silenceTimeout = null;
        }
    }

    private void handleTranscript(String transcript) {
        updateNotification("Thinking…");
        new Thread(() -> {
            String reply;
            try {
                reply = askDivya(transcript);
            } catch (Exception error) {
                reply = "अभी जवाब नहीं दे पाई। फिर से कोशिश करें।";
            }
            finishWithSpeech(reply);
        }).start();
    }

    /** POSTs to divya-chat, same contract as services/divyaChat.js (pairing
     * code gate, {message, history} body, {status, reply} response). No
     * chat history is sent from this native path -- kept a self-contained
     * fresh turn each wake, since carrying JS's in-memory history natively
     * would need a second sync channel for little benefit on a short
     * wake-triggered command. */
    private String askDivya(String message) throws Exception {
        String supabaseUrl = DivyaPrefs.supabaseUrl(this);
        String anonKey = DivyaPrefs.supabaseAnonKey(this);
        String pairingCode = DivyaPrefs.pairingCode(this);
        if (supabaseUrl.isEmpty() || anonKey.isEmpty() || pairingCode.isEmpty()) {
            return "सेटअप अधूरा है। ऐप खोलकर फिर से जोड़ें।";
        }

        JSONObject body = new JSONObject();
        body.put("pairing_code", pairingCode);
        body.put("message", message);
        body.put("history", new JSONArray());

        URL url = new URL(supabaseUrl + "/functions/v1/divya-chat");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("apikey", anonKey);
            connection.setRequestProperty("Authorization", "Bearer " + anonKey);
            connection.setConnectTimeout(8_000);
            connection.setReadTimeout(15_000);
            connection.setDoOutput(true);
            try (OutputStream out = connection.getOutputStream()) {
                out.write(body.toString().getBytes(StandardCharsets.UTF_8));
            }

            int status = connection.getResponseCode();
            java.io.InputStream stream = status >= 200 && status < 300
                ? connection.getInputStream()
                : connection.getErrorStream();
            String responseBody = readStream(stream);
            JSONObject json = new JSONObject(responseBody);
            if (!"ok".equals(json.optString("status")) || json.optString("reply").isEmpty()) {
                return "अभी जवाब नहीं दे पाई। फिर से कोशिश करें।";
            }
            return json.getString("reply");
        } finally {
            connection.disconnect();
        }
    }

    private String readStream(java.io.InputStream stream) throws Exception {
        if (stream == null) return "{}";
        java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
        byte[] chunk = new byte[1024];
        int read;
        while ((read = stream.read(chunk)) != -1) buffer.write(chunk, 0, read);
        return buffer.toString("UTF-8");
    }

    private void finishWithSpeech(String text) {
        updateNotification("Speaking…");
        tts = new TextToSpeech(this, status -> {
            if (status != TextToSpeech.SUCCESS || tts == null) {
                stopSelf();
                return;
            }
            boolean isHindi = containsDevanagari(text);
            tts.setLanguage(isHindi ? new Locale("hi", "IN") : Locale.US);
            tts.setSpeechRate(0.95f);
            tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override public void onStart(String utteranceId) {}
                @Override public void onDone(String utteranceId) { stopSelf(); }
                @Override public void onError(String utteranceId) { stopSelf(); }
            });
            Bundle params = new Bundle();
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, params, "divya_wake_reply");
        });
    }

    private void finishSilently() {
        stopSelf();
    }

    private boolean containsDevanagari(String text) {
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c >= 0x0900 && c <= 0x097F) return true;
        }
        return false;
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null || manager.getNotificationChannel(CHANNEL_ID) != null) return;
        NotificationChannel channel = new NotificationChannel(
            CHANNEL_ID,
            "Voice command",
            NotificationManager.IMPORTANCE_HIGH
        );
        channel.setDescription("Shows while the microphone is actively listening for a command.");
        channel.setShowBadge(false);
        manager.createNotificationChannel(channel);
    }

    private Notification buildNotification(String text) {
        Intent launch = new Intent(this, MainActivity.class);
        launch.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT
            | (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent contentIntent = PendingIntent.getActivity(this, 0, launch, flags);

        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Divya Drishti")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setOngoing(true)
            .setContentIntent(contentIntent)
            .build();
    }

    private void updateNotification(String text) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) manager.notify(NOTIFICATION_ID, buildNotification(text));
    }
}
