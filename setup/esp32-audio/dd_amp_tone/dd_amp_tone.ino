/**
 * Divya Drishti — ESP32 MAX98357A tone (Arduino-ESP32 3.x / i2s_std)
 * Agreed map: LRCLK=25, BCLK=27, DIN=26
 */
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include <math.h>

static const gpio_num_t PIN_LRC  = GPIO_NUM_25;
static const gpio_num_t PIN_BCLK = GPIO_NUM_27;
static const gpio_num_t PIN_DIN  = GPIO_NUM_26;
static const int PIN_LED = 2;  // DevKit onboard LED

static const int SAMPLE_RATE = 44100;
static const float FREQ_HZ = 440.0f;
static const int FRAMES = 256;

static i2s_chan_handle_t tx_handle = NULL;

static bool init_i2s() {
  i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  chan_cfg.auto_clear = true;
  esp_err_t err = i2s_new_channel(&chan_cfg, &tx_handle, NULL);
  Serial.printf("i2s_new_channel=%s\n", esp_err_to_name(err));
  if (err != ESP_OK) return false;

  i2s_std_config_t std_cfg = {
    .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
    .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
    .gpio_cfg = {
      .mclk = I2S_GPIO_UNUSED,
      .bclk = PIN_BCLK,
      .ws = PIN_LRC,
      .dout = PIN_DIN,
      .din = I2S_GPIO_UNUSED,
      .invert_flags = {
        .mclk_inv = false,
        .bclk_inv = false,
        .ws_inv = false,
      },
    },
  };

  err = i2s_channel_init_std_mode(tx_handle, &std_cfg);
  Serial.printf("i2s_channel_init_std_mode=%s\n", esp_err_to_name(err));
  if (err != ESP_OK) return false;

  err = i2s_channel_enable(tx_handle);
  Serial.printf("i2s_channel_enable=%s\n", esp_err_to_name(err));
  return err == ESP_OK;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  pinMode(PIN_LED, OUTPUT);
  Serial.println();
  Serial.println("=== DD amp tone v3 (i2s_std) ===");
  Serial.println("Pins: LRCLK=GPIO25  BCLK=GPIO27  DIN=GPIO26");
  Serial.println("HARDWARE MUST: amp SD->VIN, amp GND==ESP32 GND, speaker on L+/L-");

  if (!init_i2s()) {
    Serial.println("I2S init FAILED — blinking fast");
    while (true) {
      digitalWrite(PIN_LED, !digitalRead(PIN_LED));
      delay(100);
    }
  }
  Serial.println("I2S OK — 440Hz full-scale tone");
}

void loop() {
  static float phase = 0.0f;
  static uint32_t n = 0;
  const float step = 2.0f * (float)M_PI * FREQ_HZ / (float)SAMPLE_RATE;
  int16_t samples[FRAMES * 2];

  for (int i = 0; i < FRAMES; i++) {
    int16_t s = (int16_t)(sinf(phase) * 30000.0f);
    samples[i * 2] = s;
    samples[i * 2 + 1] = s;
    phase += step;
    if (phase > 2.0f * (float)M_PI) phase -= 2.0f * (float)M_PI;
  }

  size_t written = 0;
  esp_err_t err = i2s_channel_write(tx_handle, samples, sizeof(samples), &written, portMAX_DELAY);

  // slow blink = alive + streaming
  if ((++n % 80) == 0) {
    digitalWrite(PIN_LED, !digitalRead(PIN_LED));
    Serial.printf("write=%s bytes=%u\n", esp_err_to_name(err), (unsigned)written);
  }
}
