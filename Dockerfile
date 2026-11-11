FROM eclipse-temurin:17-jdk-jammy
ENV DEBIAN_FRONTEND=noninteractive ANDROID_HOME=/opt/android ANDROID_SDK_ROOT=/opt/android
ENV PATH=/opt/android/cmdline-tools/latest/bin:/opt/android/platform-tools:/opt/android/emulator:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends wget unzip python3 libgl1 libpulse0 libnss3 libx11-6 libxcb1 libxcomposite1 libxcursor1 libxi6 libxrandr2 libxtst6 libasound2 libdbus-1-3 && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/android/cmdline-tools && wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -O /tmp/tools.zip && unzip -q /tmp/tools.zip -d /tmp/tools && mv /tmp/tools/cmdline-tools /opt/android/cmdline-tools/latest && rm /tmp/tools.zip
RUN yes | sdkmanager --licenses >/dev/null || true
RUN sdkmanager --install "platform-tools" "emulator" "system-images;android-30;google_apis_playstore;x86_64"
RUN echo no | avdmanager create avd -n androidtest -k "system-images;android-30;google_apis_playstore;x86_64" --device "pixel_5"
COPY android_test_server.py /app/android_test_server.py
WORKDIR /app
EXPOSE 8080
CMD ["python3","android_test_server.py"]
