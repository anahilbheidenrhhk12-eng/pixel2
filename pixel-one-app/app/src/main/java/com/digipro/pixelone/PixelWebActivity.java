package com.digipro.pixelone;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class PixelWebActivity extends Activity {
    private static final String ONE_URL = "https://one.google.com/";
    private static final String UA = "Mozilla/5.0 (Linux; Android 17; Pixel 11 Pro XL "
        + "Build/CD1A.261005.003; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
        + "Version/4.0 Chrome/157.0.8103.50 Mobile Safari/537.36";
    private WebView web;
    private TextView status;

    private int dp(int n) {
        return (int)(n * getResources().getDisplayMetrics().density + .5f);
    }

    private Button action(String text) {
        Button view = new Button(this);
        view.setAllCaps(false);
        view.setText(text);
        view.setTextSize(12);
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(7, 19, 33));

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(7, 19, 33));
        setContentView(root);

        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setPadding(dp(12), dp(9), dp(12), dp(9));
        toolbar.setOrientation(LinearLayout.VERTICAL);
        toolbar.setBackgroundColor(Color.rgb(18, 36, 56));
        root.addView(toolbar);

        status = new TextView(this);
        status.setText("PIXEL 11 PRO XL  /  GOOGLE ONE WEB");
        status.setTextColor(Color.rgb(36, 227, 188));
        status.setTextSize(12);
        status.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        toolbar.addView(status);

        LinearLayout bar = new LinearLayout(this);
        toolbar.addView(bar);
        Button nativeApp = action("GOOGLE ONE APP");
        Button reload = action("RELOAD");
        bar.addView(nativeApp, new LinearLayout.LayoutParams(0, dp(48), 2));
        bar.addView(reload, new LinearLayout.LayoutParams(0, dp(48), 1));

        nativeApp.setOnClickListener(v -> openOfficialApp());
        reload.setOnClickListener(v -> {
            if (web != null) web.reload();
        });

        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setUserAgentString(UA);
        settings.setSupportZoom(true);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String host = uri.getHost();
                if (host != null && host.equalsIgnoreCase("accounts.google.com")) {
                    // Never request Google credentials in an embedded WebView.
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, uri));
                        status.setText("Google sign-in opened in system browser");
                    } catch (ActivityNotFoundException e) {
                        status.setText("Browser unavailable");
                    }
                    return true;
                }
                return false;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                status.setText("PIXEL WEB  /  " + Uri.parse(url).getHost());
                // Browser-only profile fields; they do not modify Android OS
                // identity, native app signatures or system account state.
                view.evaluateJavascript(
                    "(function(){try{"
                    + "Object.defineProperty(navigator,'hardwareConcurrency',{configurable:true,get:()=>7});"
                    + "Object.defineProperty(navigator,'deviceMemory',{configurable:true,get:()=>16});"
                    + "Object.defineProperty(navigator,'maxTouchPoints',{configurable:true,get:()=>5});"
                    + "}catch(e){}})();", null);
            }
        });
        web.loadUrl(ONE_URL);
    }

    void openOfficialApp() {
        Intent launch = getPackageManager().getLaunchIntentForPackage(MainActivity.ONE_PACKAGE);
        if (launch != null) {
            startActivity(launch);
        } else {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(
                "https://play.google.com/store/apps/details?id=" + MainActivity.ONE_PACKAGE)));
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) web.destroy();
        super.onDestroy();
    }
}
