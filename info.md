<p align="center">
  <img src="https://raw.githubusercontent.com/carlosespinosamoreno99/fermax_nowifi/main/images/icon.png" width="96" height="96" alt="Fermax NOWIFI Logo">
</p>

# Fermax NOWIFI para Home Assistant (HACS)

Integración completa para sistemas de videoportero **Fermax Duox Me** en instalaciones **NOWIFI / 4G (Placas Skyline y Cityline)**.

Permite conectar Home Assistant directamente con la nube Fermax Blue sin necesidad de monitor con conexión Wi-Fi en la vivienda.

---

### ✨ Características Destacadas

* 🚪 **Apertura de Puerta Inteligente:**
  * **Modo In-Call:** Si la cámara está activa o el timbre está sonando, usa `/deviceaction/api/v1/device/incall/opendoor` para desbloquear el pestillo en caliente.
  * **Modo en Reposo:** Si la placa está inactiva, utiliza `directOpenDoorNoWifi` directamente sobre la placa exterior 4G.
* 🔔 **Detección Instantánea de Timbre:**
  * Sensor binario ultrarrápido vía notificaciones push de **Firebase Cloud Messaging (FCM)** (< 400 ms).
  * **Auto-encendido de Cámara:** Al recibir la llamada, la integración activa automáticamente el flujo de vídeo para que aparezca en tus paneles o notificaciones móviles de HA.
* 📹 **Switch de Cámara con Temporizador de 65 Segundos:**
  * Enciende la cámara a petición del usuario.
  * Se apaga automáticamente al cumplirse **1 minuto y 5 segundos (65s)** para evitar agotar la batería o bloquear la placa exterior.
  * Si el usuario apaga el switch antes, la cámara se desconecta de inmediato.
* 📺 **Entidad de Cámara en Tiempo Real:**
  * Streaming de vídeo nativo a **720x480 @ 25 FPS** mediante Mediasoup SFU WebRTC.
  * Distintivo `● LIVE [HH:MM:SS]` en tiempo real.
* 💡 **Relé Auxiliar / Luz de Cortesía (F1):**
  * Pulsador para encender la luz o activar automatizaciones secundarias.
* 🚪 **Apertura de Puerta Secundaria:**
  * Soporte para cancela o segunda puerta (Relé #2).
* ⚙️ **Configuración Cero Esfuerzo (Zero-Config):**
  * Solo introduces tu usuario (correo) y contraseña de Fermax Blue.
  * Todos los parámetros técnicos del proyecto Firebase (`fermax-blue`) vienen integrados de serie.
