{
  lib,
  stdenv,
  buildNpmPackage,
  fetchFromGitHub,
  nixosTests,
}:

buildNpmPackage rec {
  pname = "jitsi-meet";
  version = "2.0.9955";

  src = fetchFromGitHub {
    owner = "jitsi";
    repo = "jitsi-meet";
    tag = "stable/jitsi-meet_${builtins.substring 4 (-1) version}";
    hash = "sha256-WvLzq2qzRPCDCpR8BQpTCaPubCBKBcV9LBcjmkEZPdc=";
  };

  npmDepsHash = "sha256-OIZV56mvH81RpYs7Fw8HwltH9l4Hz2NtLWAYbOaklOM=";
  makeCacheWritable = true;

  postPatch = ''
    substituteInPlace package.json \
      --replace-fail '"scripts": {' '"scripts": {"build": "make",'
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/css
    cp --no-preserve=mode -prt $out/ \
      libs \
      static \
      sounds \
      fonts \
      images \
      lang \
      *.html \
      config.js \
      interface_config.js \
      pwa-worker.js \
      manifest.json \
      resources/robots.txt
    cp --no-preserve=mode css/all.css $out/css/
    runHook postInstall
  '';


  # Test requires running Jitsi Videobridge and Jicofo which are Linux-only
  passthru.tests = lib.optionalAttrs stdenv.hostPlatform.isLinux {
    single-host-smoke-test = nixosTests.jitsi-meet;
  };

  passthru.updateScript = ./update.sh;

  meta = with lib; {
    description = "Secure, Simple and Scalable Video Conferences";
    longDescription = ''
      Jitsi Meet is an open-source (Apache) WebRTC JavaScript application that uses Jitsi Videobridge
      to provide high quality, secure and scalable video conferences.
    '';
    homepage = "https://github.com/jitsi/jitsi-meet";
    license = licenses.asl20;
    maintainers = teams.jitsi.members;
    platforms = platforms.all;
  };
}
