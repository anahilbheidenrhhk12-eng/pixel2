package com.digipro.pixelone;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

public class MainActivity extends Activity {
    public static final String ONE_PACKAGE = "com.google.android.apps.subscriptions.red";
    private static final int BG = Color.rgb(7, 19, 33);
    private static final int CARD = Color.rgb(18, 36, 56);
    private static final int TEAL = Color.rgb(36, 227, 188);
    private static final int WHITE = Color.rgb(247, 251, 255);
    private static final int MUTED = Color.rgb(157, 176, 193);
    private TextView state;

    private int dp(float value) {
        return (int)(value * getResources().getDisplayMetrics().density + .5f);
    }

    private GradientDrawable background(int fill, int radius, boolean outline) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setCornerRadius(dp(radius));
        if (outline) shape.setStroke(dp(1), Color.rgb(45, 70, 90));
        return shape;
    }

    private LinearLayout.LayoutParams layout(int top) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2);
        p.topMargin = dp(top);
        return p;
    }

    private TextView title(String text, int sp, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextSize(sp);
        view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private Button button(String text, boolean primary) {
        Button view = new Button(this);
        view.setText(text);
        view.setAllCaps(false);
        view.setTextSize(primary ? 16 : 14);
        view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        view.setTextColor(primary ? BG : WHITE);
        view.setBackground(background(primary ? TEAL : CARD, 15, !primary));
        view.setElevation(0);
        view.setMinimumHeight(dp(58));
        view.setPadding(dp(12), dp(10), dp(12), dp(10));
        return view;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);
        LinearLayout root = new LinearLayout(this);
        root.setPadding(dp(24), dp(24), dp(24), dp(30));
        root.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(root);
        setContentView(scroll);

        TextView label = title("DIGI PRO / PIXEL ONE", 12, TEAL, true);
        label.setLetterSpacing(.13f);
        root.addView(label);
        root.addView(title("Pixel browser +\nGoogle One", 31, WHITE, true), layout(17));
        TextView description = title(
            "One-tap Google One launcher and Pixel 11 browser-profile experiment.",
            14, MUTED, false);
        root.addView(description, layout(12));

        LinearLayout profile = new LinearLayout(this);
        profile.setOrientation(LinearLayout.VERTICAL);
        profile.setPadding(dp(18), dp(19), dp(18), dp(20));
        profile.setBackground(background(CARD, 19, true));
        root.addView(profile, layout(26));

        TextView caption = title("PIXEL BROWSER PROFILE", 11, TEAL, true);
        caption.setLetterSpacing(.13f);
        profile.addView(caption);
        profile.addView(title("Pixel 11 Pro XL", 23, WHITE, true), layout(12));
        profile.addView(title("Android 17  •  mobile Chromium-style UA", 13, MUTED, false), layout(6));
        View divider = new View(this);
        divider.setBackgroundColor(Color.rgb(45, 70, 90));
        LinearLayout.LayoutParams sep = layout(17);
        sep.height = dp(1);
        profile.addView(divider, sep);
        state = title("Checking installed apps…", 14, WHITE, false);
        profile.addView(state, layout(16));
        profile.addView(title("Physical phone: " + Build.MANUFACTURER + " " + Build.MODEL,
            12, MUTED, false), layout(8));

        Button open = button("OPEN GOOGLE ONE", true);
        root.addView(open, layout(27));
        open.setOnClickListener(v -> openGoogleOne());

        Button browser = button("PIXEL BROWSER MODE", false);
        root.addView(browser, layout(12));
        browser.setOnClickListener(v ->
            startActivity(new Intent(MainActivity.this, PixelWebActivity.class)));

        Button account = button("ADD / SWITCH GOOGLE ACCOUNT", false);
        root.addView(account, layout(12));
        account.setOnClickListener(v -> openAccounts());

        TextView note = title(
            "Google One opens as its official Android app. The Pixel browser mode is a separate test using a Pixel-style web profile.",
            12, MUTED, false);
        root.addView(note, layout(24));
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (state != null) {
            boolean installed = getPackageManager().getLaunchIntentForPackage(ONE_PACKAGE) != null;
            state.setText(installed ? "●  Google One app installed and ready"
                                   : "○  Google One not installed — tap Open to install");
        }
    }

    void openGoogleOne() {
        Intent launch = getPackageManager().getLaunchIntentForPackage(ONE_PACKAGE);
        if (launch != null) {
            startActivity(launch);
            return;
        }
        try {
            Intent market = new Intent(Intent.ACTION_VIEW,
                Uri.parse("market://details?id=" + ONE_PACKAGE));
            market.setPackage("com.android.vending");
            startActivity(market);
        } catch (ActivityNotFoundException e) {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(
                    "https://play.google.com/store/apps/details?id=" + ONE_PACKAGE)));
            } catch (ActivityNotFoundException noBrowser) {
                Toast.makeText(this, "Play Store unavailable", Toast.LENGTH_LONG).show();
            }
        }
    }

    void openAccounts() {
        try {
            startActivity(new Intent("android.settings.ADD_ACCOUNT_SETTINGS"));
        } catch (ActivityNotFoundException ex) {
            try {
                startActivity(new Intent(Settings.ACTION_SYNC_SETTINGS));
            } catch (ActivityNotFoundException ignored) {
                Toast.makeText(this, "Open Android Settings > Accounts", Toast.LENGTH_LONG).show();
            }
        }
    }
}
