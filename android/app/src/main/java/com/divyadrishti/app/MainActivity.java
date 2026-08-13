package com.divyadrishti.app;

import android.os.Bundle;
import android.webkit.WebSettings;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(LocalDeviceDiscoveryPlugin.class);
        registerPlugin(BackgroundGuardianPlugin.class);
        super.onCreate(savedInstanceState);
        // The nearby glasses link is an explicitly paired, same-Wi-Fi HTTP
        // endpoint. Cloud traffic continues to use HTTPS.
        getBridge().getWebView().getSettings()
            .setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
    }
}
