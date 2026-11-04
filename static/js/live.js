/* ==========================================================================
   live.js — extras for the live screens (kitchen board, ready to serve).

   1. Sound: a short beep when the number in data-alert-count grows after a
      refresh (a new KOT in the kitchen, new food ready for waiters).
      Browsers only allow sound after a tap, so it starts off; the
      "Sound off / on" button switches it and is remembered on this device.
   2. Full screen button (kitchen tablet).
   ========================================================================== */

(function () {
  /* ---------------------------------------------------------------- sound */
  const SOUND_KEY = "resto-sound";
  const button = document.getElementById("soundToggle");
  let soundOn = false;
  let audio = null;

  try {
    soundOn = localStorage.getItem(SOUND_KEY) === "on";
  } catch (e) {}

  function showSoundButton() {
    if (!button) return;
    button.setAttribute("aria-pressed", soundOn ? "true" : "false");
    button.querySelector("i").className = soundOn ? "bi bi-volume-up" : "bi bi-volume-mute";
    button.querySelector("span").textContent = soundOn ? "Sound on" : "Sound off";
    button.classList.toggle("btn-primary", soundOn);
    button.classList.toggle("btn-light", !soundOn);
  }

  function beep() {
    if (!soundOn) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      // two short tones
      [0, 0.22].forEach(function (start, index) {
        const tone = audio.createOscillator();
        const volume = audio.createGain();
        tone.frequency.value = index ? 1046 : 784;
        volume.gain.setValueAtTime(0.25, audio.currentTime + start);
        volume.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + start + 0.2);
        tone.connect(volume).connect(audio.destination);
        tone.start(audio.currentTime + start);
        tone.stop(audio.currentTime + start + 0.2);
      });
    } catch (e) {}
  }

  if (button) {
    showSoundButton();
    button.addEventListener("click", function () {
      soundOn = !soundOn;
      try {
        localStorage.setItem(SOUND_KEY, soundOn ? "on" : "off");
      } catch (e) {}
      showSoundButton();
      beep(); // the tap also unlocks sound, and lets them hear it
    });
  }

  // remember the count, and beep when a refresh brings a bigger one
  let lastCount = null;
  function readCount() {
    const box = document.querySelector("[data-alert-count]");
    return box ? parseInt(box.dataset.alertCount, 10) || 0 : null;
  }
  lastCount = readCount();

  document.body.addEventListener("htmx:afterSettle", function () {
    const count = readCount();
    if (count === null) return;
    if (lastCount !== null && count > lastCount) beep();
    lastCount = count;
  });

  /* ----------------------------------------------------------- full screen */
  const fullButton = document.getElementById("fullScreen");
  if (fullButton && document.documentElement.requestFullscreen) {
    fullButton.addEventListener("click", function () {
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        document.documentElement.requestFullscreen();
      }
    });
  } else if (fullButton) {
    fullButton.hidden = true;
  }
})();
