#!/bin/sh
# Gera o APK do controle remoto da F.R.I.D.A.Y. sem Gradle (aapt2 + javac + d8 + apksigner). Saída: friday-commercial.apk
set -e
D="$(cd "$(dirname "$0")" && pwd)"
A="$HOME/.local/android"; export JAVA_HOME="$(ls -d "$A"/jdk-17*)"; PATH="$JAVA_HOME/bin:$PATH"
BT="$A/sdk/build-tools/34.0.0"; JAR="$A/sdk/platforms/android-34/android.jar"
B="$D/build"; rm -rf "$B"; mkdir -p "$B/res" "$B/gen" "$B/cls" "$B/dex" "$D/dist"
"$BT/aapt2" compile --dir "$D/res" -o "$B/res/"
mkdir -p "$B/assets" && cp -r "$D/assets/." "$B/assets/" && rm -f "$B/assets/voz_dono.json"        # perfil de voz é do dono: nunca vai no APK comercial
"$BT/aapt2" link -o "$B/base.apk" -I "$JAR" --manifest "$D/AndroidManifest.xml" -A "$B/assets" --java "$B/gen" "$B"/res/*.flat --auto-add-overlay
find "$D/src" "$B/gen" -name '*.java' | sed 's/.*/"&"/' > "$B/fontes.txt"          # o caminho tem espaço: lista via @arquivo
ORT="$A/libs/ort"                                                                    # ONNX Runtime (voz Supertonic)
javac -source 11 -target 11 -nowarn -classpath "$JAR:$ORT/classes.jar" -d "$B/cls" @"$B/fontes.txt" > "$B/javac.log" 2>&1 \
  || { grep -v "^warning\|^Note" "$B/javac.log"; echo "FALHOU a compilação Java"; exit 1; }
find "$B/cls" -name '*.class' > "$B/classes.txt"
"$BT/d8" --lib "$JAR" --min-api 26 --output "$B/dex" @"$B/classes.txt" "$ORT/classes.jar"
cp "$B/base.apk" "$B/unsigned.apk"
python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1],'a').write(sys.argv[2],'classes.dex')" "$B/unsigned.apk" "$B/dex/classes.dex"
# cérebro local (llama.cpp): lib/arm64-v8a/libfriday_llm.so (gerada por build_jni.sh)
for so in libonnxruntime.so libonnxruntime4j_jni.so; do
  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1],'a',zipfile.ZIP_DEFLATED).write(sys.argv[2],'lib/arm64-v8a/'+sys.argv[3])" "$B/unsigned.apk" "$ORT/jni/arm64-v8a/$so" "$so"
done
[ -f "$D/jniLibs/arm64-v8a/libfriday_llm.so" ] && python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1],'a',zipfile.ZIP_DEFLATED).write(sys.argv[2],'lib/arm64-v8a/libfriday_llm.so')" "$B/unsigned.apk" "$D/jniLibs/arm64-v8a/libfriday_llm.so"
"$BT/zipalign" -f -p 4 "$B/unsigned.apk" "$B/aligned.apk"
KS="$D/friday.keystore"
[ -f "$KS" ] || keytool -genkeypair -keystore "$KS" -alias friday -keyalg RSA -keysize 2048 -validity 10000 -storepass fridaypass -keypass fridaypass -dname "CN=FRIDAY,O=Integra,C=BR" >/dev/null 2>&1
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:fridaypass --key-pass pass:fridaypass --out "$D/friday-commercial.apk" "$B/aligned.apk"
"$BT/apksigner" verify "$D/friday-commercial.apk" && ls -la "$D/friday-commercial.apk"
