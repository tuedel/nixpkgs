{
  lib,
  stdenv,
  fetchurl,
  dpkg,
  nixosTests,
  olm,
}:
stdenv.mkDerivation rec {
  pname = "jitsi-meet";
  version = "1.0.8339";

  srcs = [
    (fetchurl {
      name = "jitsi-meet-web.deb";
      url = "https://download.jitsi.org/stable/${pname}-web_${version}-1_all.deb";
      hash = "sha256-eqHIW88pEZkU/dwNhxEF8VJ7iMLErWdAGHJYoCR/ZNE=";
    })
    (fetchurl {
      name = "jitsi-meet-web-config.deb";
      url = "https://download.jitsi.org/stable/${pname}-web-config_${version}-1_all.deb";
      hash = "sha256-HrSGYNU97Fr9+xPsEmAwcT/pEdfooYA6u8D+2nEVuIY=";
    })
  ];

  nativeBuildInputs = [ dpkg ];

  dontBuild = true;

  installPhase = ''
    runHook preInstall
    mv usr/share/${pname} $out
    mv usr/share/${pname}-web-config/config.js $out/
    runHook postInstall
  '';

  # Test requires running Jitsi Videobridge and Jicofo which are Linux-only
  passthru.tests = lib.optionalAttrs stdenv.hostPlatform.isLinux {
    single-host-smoke-test = nixosTests.jitsi-meet;
  };

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
    inherit (olm.meta) knownVulnerabilities;
  };
}
