<p align="center">
  <img src="https://raw.githubusercontent.com/EspiThekiller/fermax_nowifi/main/images/icon.png" width="120" height="120" alt="Fermax NOWIFI Logo">
</p>

<h1 align="center">Fermax NOWIFI para Home Assistant</h1>

<p align="center">
  <a href="https://github.com/hacs/default"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge" alt="HACS Badge"></a>
  <a href="https://www.home-assistant.io/"><img src="https://img.shields.io/badge/Home--Assistant-2024.6+-blue.svg?style=for-the-badge&logo=home-assistant" alt="Home Assistant"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Version-1.0.3-emerald.svg?style=for-the-badge" alt="Version 1.0.3">
</p>

Integración completa para **Home Assistant (HACS)** diseñada específicamente para sistemas de videoportero **Fermax Duox Me** en instalaciones **NOWIFI / 4G** (placas exteriores Skyline y Cityline con módem 4G integrado).

Permite recibir llamadas de timbre en tiempo real, visualizar el streaming de la cámara de la placa exterior con latencia ultrabaja, abrir puertas de forma inteligente y automatizar tu acceso desde Home Assistant **sin necesidad de disponer de un monitor con Wi-Fi en el interior de la vivienda**.

---

## 📌 ¿Por qué Fermax NOWIFI?

En las instalaciones tradicionales con monitor Wi-Fi, las órdenes de apertura y encendido se dirigen a la IP local o al ID del monitor interior. Sin embargo, en las comunidades y viviendas con sistema **NOWIFI (4G)**:
1. La comunicación se realiza directamente entre la nube de Fermax y la **placa exterior 4G**.
2. Las órdenes de vídeo y llamada se transmiten mediante notificaciones push de **Google Firebase Cloud Messaging (FCM)** con salas WebRTC dinámicas (**Mediasoup SFU**).
3. **Apertura de puerta condicional:** Durante una llamada o autoencendido de cámara, el portero entra en estado `MobileAutoOnState` y rechaza órdenes estándar; requiere el endpoint especializado de apertura en llamada (`/deviceaction/api/v1/device/incall/opendoor`).

Esta integración implementa de forma nativa todos estos contratos de datos descubiertos mediante ingeniería inversa, garantizando fiabilidad absoluta.

---

## 🚀 Características Principales

| Entidad | Tipo | Descripción |
| :--- | :--- | :--- |
| **Abrir Puerta Principal** | `button` | Pulsador inteligente: si la cámara está activa abre vía `in-call`, si está en reposo usa `directOpenDoorNoWifi`. |
| **Abrir Puerta 2 / Cancela** | `button` | Abre la cancela o segunda puerta asociada (Relé #2). |
| **Luz de Cortesía (F1)** | `button` | Activa la función auxiliar F1 (luz de cortesía / relé auxiliar). |
| **Timbre** | `binary_sensor` | Detección de llamada entrante en menos de 400 ms vía FCM. **Activa la cámara de forma automática.** |
| **Conexión Nube** | `binary_sensor` | Monitoriza el estado de la conexión push con Firebase/Fermax. |
| **Cámara Exterior** | `switch` | Enciende la cámara a demanda. **Cuenta con temporizador automático de 1 min y 5 seg (65s)** para apagarse solo, o se apaga inmediatamente si se conmuta a OFF antes. |
| **Cámara Placa Exterior** | `camera` | Emisión de vídeo en directo a **720x480 @ 25 FPS** con distintivo `● LIVE [HH:MM:SS]`. |
| **Estado de la Placa** | `sensor` | Muestra en tiempo real: *En reposo*, *Llamando al timbre*, *Cámara en directo*, *Placa ocupada*. |
| **Última Llamada** | `sensor` | Registra la hora exacta en la que se pulsó el timbre por última vez. |
| **Último Rostro Reconocido** | `sensor` | Muestra el nombre de la persona autorizada identificada por el microservicio facial y su confianza. |

---

## 🏗️ Diagrama de Arquitectura

```
┌───────────────────────┐         RTP H.264 Video         ┌─────────────────────────┐
│ Placa Fermax 4G       │────────────────────────────────>│ Servidor Mediasoup SFU  │
│ (Skyline / Cityline)  │                                 │ (signaling-pro-duoxme)  │
└───────────────────────┘                                 └────────────┬────────────┘
            ▲                                                          │
            │ Señalización Cloud                                       │ Socket.IO
            │                                                          ▼
┌───────────┴───────────┐         Push Notification       ┌─────────────────────────┐
│ Fermax Blue Cloud     │────────────────────────────────>│ Home Assistant          │
│ (REST API v1 / v2)    │    (RoomId, Token, AutoOn)      │ (fermax_nowifi)         │
└───────────────────────┘                                 └────────────┬────────────┘
            ▲                                                          │
            │                                                          │ MJPEG 720x480
            │ HTTP (Apertura / AutoOn)                                 ▼
┌───────────┴───────────────────────────────────────────────────────────────────────┐
│ Dashboard Lovelace / App Móvil Home Assistant (Pulsador + Notificaciones)         │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Instalación

### Opción 1: A través de HACS (Recomendado)

1. Abre **Home Assistant** y entra en **HACS** > **Integraciones**.
2. Haz clic en los tres puntos de la esquina superior derecha y selecciona **Repositorios personalizados**.
3. Añade la URL de este repositorio:
   ```
   https://github.com/EspiThekiller/fermax_nowifi
   ```
   * Tipo: **Integración**
4. Haz clic en **Añadir**, busca **Fermax NOWIFI** y pulsa **Descargar**.
5. Reinicia Home Assistant.

### Opción 2: Instalación Manual

1. Descarga el repositorio o la carpeta `custom_components/fermax_nowifi`.
2. Copia la carpeta `fermax_nowifi` dentro del directorio `config/custom_components/` de tu servidor Home Assistant:
   ```
   config/
   └── custom_components/
       └── fermax_nowifi/
           ├── __init__.py
           ├── manifest.json
           ├── ...
   ```
3. Reinicia Home Assistant.

---

## ⚙️ Configuración (Zero-Config)

¡Olvídate de buscar claves de Google Firebase o tokens ocultos! La integración automatiza todo el proceso:

1. Ve a **Ajustes** > **Dispositivos y Servicios** > **Añadir Integración**.
2. Busca **Fermax NOWIFI**.
3. Introduce tu **correo electrónico** y **contraseña** de la aplicación móvil Fermax Blue.
4. Pulsa **Enviar**.

La integración:
* Validará tus credenciales con Fermax OAuth2.
* Detectará automáticamente el identificador de tu vivienda (`house_id`), el identificador de la placa exterior (`panel_id`) y los números de relé.
* Generará un token de notificación push exclusivo con Google FCM y lo vinculará a tu cuenta en Fermax Cloud.
* Creará el dispositivo con todas las entidades listas para usar.

---

## ⏱️ Temporizador de Cámara (1 min y 5 seg)

Por defecto, para proteger el consumo de la placa exterior y evitar bloqueos en el bus Duox:
* Al activar el interruptor **Cámara Exterior** (o cuando llaman al timbre), la cámara se enciende y arranca un temporizador interno de **65 segundos** (1 minuto y 5 segundos).
* Transcurrido ese tiempo, la cámara y el streaming WebRTC se desconectan automáticamente regresando la placa a reposo.
* Si el usuario apaga el switch manualmente antes de los 65 segundos, la sesión se corta en el acto sin esperar al temporizador.
* Puedes ajustar este tiempo en cualquier momento desde **Ajustes** > **Integraciones** > **Fermax NOWIFI** > **Configurar** (deslizador de 10 a 300 segundos).

---

## 💡 Ejemplos de Automatizaciones

### 1. Notificación al móvil con vídeo y botón de apertura cuando llaman al timbre

```yaml
alias: "Portero: Notificación con Cámara y Botón de Apertura"
description: "Envía una notificación al smartphone cuando pulsan el timbre exterior con acceso directo al vídeo y botón para abrir la puerta."
trigger:
  - platform: state
    entity_id: binary_sensor.timbre
    to: "on"
action:
  - service: notify.notify
    data:
      title: "🔔 ¡Alguien está llamando a la puerta!"
      message: "Están tocando el timbre en la placa exterior."
      data:
        entity_id: camera.camara_placa_exterior
        actions:
          - action: "OPEN_FERMAX_DOOR"
            title: "🔓 Abrir Puerta"
          - action: "DISMISS"
            title: "Ignorar"

# Automatización para procesar el botón de la notificación
alias: "Portero: Abrir desde Notificación"
trigger:
  - platform: event
    event_type: mobile_app_notification_action
    event_data:
      action: "OPEN_FERMAX_DOOR"
action:
  - service: button.press
    target:
      entity_id: button.abrir_puerta_principal
```

### 2. Encender la luz de cortesía (F1) si llaman de noche

```yaml
alias: "Portero: Encender luz exterior si llaman de noche"
trigger:
  - platform: state
    entity_id: binary_sensor.timbre
    to: "on"
condition:
  - condition: sun
    after: sunset
action:
  - service: button.press
    target:
      entity_id: button.luz_de_cortesia_f1
```

---

## 🖥️ Tarjeta de Lovelace Recomendada

Puedes añadir una tarjeta **Picture Glance** en tu dashboard de Home Assistant para tener la imagen de la cámara con los controles integrados:

```yaml
type: picture-glance
title: Videoportero Fermax
camera_image: camera.camara_placa_exterior
camera_view: live
entities:
  - entity: switch.camara_exterior
  - entity: button.abrir_puerta_principal
  - entity: button.abrir_puerta_2_cancela
  - entity: button.luz_de_cortesia_f1
  - entity: binary_sensor.timbre
```

---

## 🛠️ Preguntas Frecuentes y Solución de Problemas

#### ¿Por qué sale "Placa ocupada (HTTP 409)" al activar la cámara?
Las placas Fermax no permiten dos conexiones simultáneas. Si la pantalla de la placa exterior está encendida por otra llamada reciente o alguien está tocando el teclado en la calle, Fermax Cloud responde con `HTTP 409 device_busy`. Espera unos segundos a que la placa se apague y vuelve a pulsar el interruptor.

#### ¿Funciona fuera de casa sin estar en la misma red Wi-Fi?
Sí, 100%. Esta integración opera directamente contra los servidores en la nube de Fermax y Google Firebase Cloud Messaging, por lo que funciona exactamente igual tanto si tu Home Assistant está en red local como si accedes de forma remota.

---

## 📄 Licencia

Este proyecto está bajo la licencia **MIT**. Consulta el archivo [LICENSE](LICENSE) para más detalles.
