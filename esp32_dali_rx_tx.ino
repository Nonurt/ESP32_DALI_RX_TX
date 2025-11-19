#include <Arduino.h>
#include "esp_system.h" // esp_delay_us için

// --- Pin Tanımları ---
#define DALI_TX_PIN 17
#define DALI_RX_PIN 16

// --- Global Gönderim (TX) Değişkenleri ---
uint8_t dali_forward_frame[19];
uint8_t dali_forward_frame_manchester[38];

// --- Global Alım (RX) Değişkenleri ---
volatile uint8_t dali_rx_frame[16]; 
volatile bool dali_rx_frame_ready = false; // Yeni veri geldiğini loop() a bildiren flag

// --- DALI Zamanlama (mikrosaniye) ---
#define DALI_HALF_BIT_TIME 417
#define DALI_FIRST_SAMPLE_TIME 625 
#define DALI_BIT_TIME 834

// --- FreeRTOS Değişkenleri ---
TaskHandle_t xDaliTxTaskHandle = NULL; // DALI TX görevini (task) tutacak
TaskHandle_t xDaliRxTaskHandle = NULL; // DALI RX görevini tutacak

volatile bool is_transmitting = false; // Gönderim durumu (atomik olmalı)

portMUX_TYPE daliMutex = portMUX_INITIALIZER_UNLOCKED;      // is_transmitting koruması için
portMUX_TYPE daliRxMutex = portMUX_INITIALIZER_UNLOCKED; // RX görevi için kritik bölüm


// =================================================================
//                 FONKSİYON PROTOTİPLERİ (BİLDİRİMLERİ)
// =================================================================
void init_dali_tx();
void printInstructions();
String readUserInput();
// *** GÜNCELLEME 1 ***: Komut (command) artık uint16_t
bool parseInput(const String &input, bool &is_group, bool &is_direct_arc, uint8_t &address, uint16_t &command);
void printInputInfo(bool is_group, bool is_direct_arc, uint8_t address, uint16_t command); // uint16_t
void printFrames();
void init_dali_forward_frame();
// *** GÜNCELLEME 1 ***: Komut (command) artık uint16_t
void create_dali_forward_frame_binary(bool group_or_short, bool directarcpower_or_other, uint8_t adress, uint16_t command, uint8_t *dali_forward_frame);
int int_to_binary(uint8_t *array, uint8_t message, uint8_t bit_count);
int binary_to_manchester(uint8_t *binary_message, uint8_t *manchester_message);
// =================================================================


// =================================================================
//                 DALI ALIM (RX) KESME (ISR)
// =================================================================
void IRAM_ATTR daliRxIsr() {
    detachInterrupt(digitalPinToInterrupt(DALI_RX_PIN));
    BaseType_t xHigherPriorityTaskWoken = pdFALSE;
    vTaskNotifyGiveFromISR(xDaliRxTaskHandle, &xHigherPriorityTaskWoken);
    if (xHigherPriorityTaskWoken) {
        portYIELD_FROM_ISR();
    }
}


// =================================================================
//             YÜKSEK ÖNCELİKLİ GÖNDERİM GÖREVİ (TX TASK)
// =================================================================
void daliTxTask(void *pvParameters) {
  
  Serial.println("[TX Task] Görev başlatıldı. Bildirim bekleniyor.");
  
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    portENTER_CRITICAL(&daliMutex);
    is_transmitting = true;
    portEXIT_CRITICAL(&daliMutex);
    
    Serial.println("\n[TX Task] Uyandı, gönderim başlıyor...");

    // --- KRİTİK BÖLGE BAŞLANGICI ---
    portENTER_CRITICAL(&daliMutex); 
    
    for (int i = 0; i < 38; i++) {
      digitalWrite(DALI_TX_PIN, dali_forward_frame_manchester[i]);
      ets_delay_us(DALI_HALF_BIT_TIME); // 417us
    }
    digitalWrite(DALI_TX_PIN, HIGH); // DALI Idle (mark)

    // --- KRİTİK BÖLGE BİTİŞİ ---
    portEXIT_CRITICAL(&daliMutex);

    Serial.println("[TX Task] Gönderim tamamlandı. Tekrar uykuya dalınıyor.");

    portENTER_CRITICAL(&daliMutex);
    is_transmitting = false;
    portEXIT_CRITICAL(&daliMutex);
  }
}

// =================================================================
//                YÜKSEK ÖNCELİKLİ ALIM GÖREVİ (RX TASK)
// =================================================================
void daliRxTask(void *pvParameters) {
  
  Serial.println("[RX Task] Görev başlatıldı. Kesme bekleniyor.");
  
  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

    portENTER_CRITICAL(&daliRxMutex);
    
    ets_delay_us(DALI_FIRST_SAMPLE_TIME);

    // 3. İlk 8 bit (Y-Byte)
    for (int i = 0; i < 8; i++) {
        dali_rx_frame[i] = digitalRead(DALI_RX_PIN);
        ets_delay_us(DALI_BIT_TIME); 
    }
    
    // 4. Sonraki 8 bit (X-Byte)
    for (int i = 8; i < 16; i++) {
        dali_rx_frame[i] = digitalRead(DALI_RX_PIN);
        if (i < 15) { 
            ets_delay_us(DALI_BIT_TIME); 
        }
    }
    
    portEXIT_CRITICAL(&daliRxMutex);
    
    dali_rx_frame_ready = true;
    
    vTaskDelay(pdMS_TO_TICKS(5)); // 5ms bekle
    attachInterrupt(digitalPinToInterrupt(DALI_RX_PIN), daliRxIsr, FALLING);
  }
}


// =================================================================
//                         ARDUINO SETUP
// =================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("ESP32 Dali Master TX/RX (FreeRTOS Sürümü)");

  init_dali_tx(); 
  pinMode(DALI_RX_PIN, INPUT); 

  // TX Görevi
  xTaskCreatePinnedToCore(
      daliTxTask, "DaliTxTask", 2048, NULL, 2, &xDaliTxTaskHandle, 1
  );
  
  // RX Görevi
  xTaskCreatePinnedToCore(
     daliRxTask, "DaliRxTask", 2048, NULL, 2, &xDaliRxTaskHandle, 1
  );

  delay(500); 
  attachInterrupt(digitalPinToInterrupt(DALI_RX_PIN), daliRxIsr, FALLING);
  printInstructions();
}


// =================================================================
//             ARDUINO LOOP (DÜŞÜK ÖNCELİKLİ GÖREV)
// =================================================================
void loop() {
  
  if (dali_rx_frame_ready) {
      
      portENTER_CRITICAL(&daliRxMutex);
      dali_rx_frame_ready = false;
      portEXIT_CRITICAL(&daliRxMutex);
      
      for(int i = 0; i < 16; i++){
        if(dali_rx_frame[i] == 1){
          dali_rx_frame[i] = 0;
        }
        else{
          dali_rx_frame[i] = 1;
        }
      }

     
      Serial.print("   RX (16-bit): [ ");
      for (int i = 0; i < 16; i++) {
          Serial.print(dali_rx_frame[i]);
          if (i == 7) {
              Serial.print(" | "); // Y-Byte ve X-Byte ayıracı
          }
      }
      Serial.println(" ]");
      
    
  }

  // --- TX KONTROLÜ (Serial Girdi) ---
  if (Serial.available()) {
    String input = readUserInput();
    if (input.length() > 0) {
      bool is_group, is_direct_arc;
      uint8_t address;
      uint16_t command; // *** GÜNCELLEME 2 ***: 16-bit'e çıkarıldı

      if (parseInput(input, is_group, is_direct_arc, address, command)) {
        
        bool is_busy;
        portENTER_CRITICAL(&daliMutex);
        is_busy = is_transmitting;
        portEXIT_CRITICAL(&daliMutex);

        if (is_busy) {
          Serial.println("[Main Task] HATA: TX hattı hala meşgul. Komut atlandı.");
        } else {
          //Serial.println("[Main Task] Veri ayrıştırıldı, çerçeve oluşturuluyor.");
          printInputInfo(is_group, is_direct_arc, address, command);

          init_dali_forward_frame();
          // *** GÜNCELLEME 2 ***: command değişkeni artık 16-bit
          create_dali_forward_frame_binary(is_group, is_direct_arc, address, command, dali_forward_frame);
          dali_forward_frame[0] = 1; // Start bit
          binary_to_manchester(dali_forward_frame, dali_forward_frame_manchester);
          
          printFrames();

          //Serial.println("[Main Task] TX Görevine bildirim gönderiliyor...");
          xTaskNotifyGive(xDaliTxTaskHandle);
        }
        
      } else {
        Serial.println("Geçersiz giriş formatı veya değer aralık dışı.");
      }
      
      delay(200);
      
    }
  }

  vTaskDelay(pdMS_TO_TICKS(50));
}


// =================================================================
//                       YARDIMCI FONKSİYONLAR
// =================================================================

void printInstructions() {
  Serial.println("\n-------------------------------------------------");
  Serial.println("DALI komutunu girin. Format: [g/s][d/c] [addr] [cmd]");
  Serial.println("Örnek (Standart): sd 16 165 (Short, Direct, Adres 16, Komut 165)");
  // *** DÜZELTME: İki satır tek bir komut haline getirildi ***
  Serial.println("Örnek (Özel): sc 0 258   (Short, Command, Data 0, INITIALIZE)");
  Serial.print("Giriş: ");
}

String readUserInput() {
  String input = Serial.readStringUntil('\n');
  input.trim();
  Serial.println(input); // Kullanıcının ne girdiğini ekrana bas
  return input;
}

// *** GÜNCELLEME 3: parseInput GÜNCELLENDİ ***
bool parseInput(const String &input, bool &is_group, bool &is_direct_arc, 
                uint8_t &address, uint16_t &command) { // command uint16_t
    if (input.length() < 5) return false;
    
    char typeChar = input[0];
    char commandTypeChar = input[1];
    is_group = (typeChar == 'g' || typeChar == 'G');
    is_direct_arc = (commandTypeChar == 'd' || commandTypeChar == 'D');
    
    int space1 = input.indexOf(' ');
    int space2 = input.indexOf(' ', space1 + 1);
    if (space1 == -1 || space2 == -1) return false;
    
    String addressStr = input.substring(space1 + 1, space2);
    String commandStr = input.substring(space2 + 1);
    
    address = (uint8_t)addressStr.toInt(); // Adres (veya veri) 0-255
    command = (uint16_t)commandStr.toInt(); // Komut 0-511
    
    // Adres 0-255 (Özel komutlar için veri olabilir)
    // Komut 0-511 (Özel komutları içerir)
    if (address > 255 || command > 511) {
        Serial.println("[HATA] Adres 0-255 ve Komut 0-511 aralığında olmalı.");
        return false; 
    }
    
    return true;
}

// Komut (command) uint16_t oldu
void printInputInfo(bool is_group, bool is_direct_arc, uint8_t address, uint16_t command) {
  Serial.println("--- Giriş Bilgisi ---");
  Serial.print("  Tip: "); Serial.println(is_group ? "Grup (g)" : "Kısa (s)");
  Serial.print("  Komut Tipi: "); Serial.println(is_direct_arc ? "Direct Arc (d)" : "Komut (c)");
  if (command <= 255) {
      Serial.print("  Adres (dec): "); Serial.println(address);
      Serial.print("  Komut (dec): "); Serial.println(command);
  } else {
      Serial.print("  Veri (Data) (dec): "); Serial.println(address);
      Serial.print("  Özel Komut (dec): "); Serial.println(command);
  }
}

void printFrames() {
  Serial.print("  Dali Frame (19-bit):   ");
  for (int i = 0; i < 19; i++) {
    Serial.print(dali_forward_frame[i]);
  }
  Serial.println();
  Serial.print("  Manchester (38-bit): ");
  for (int i = 0; i < 38; i++) {
    Serial.print(dali_forward_frame_manchester[i]);
  }
  Serial.println();
}

void init_dali_tx(){
    pinMode(DALI_TX_PIN, OUTPUT);
    digitalWrite(DALI_TX_PIN, HIGH);
}

void init_dali_forward_frame(){
    dali_forward_frame[17] = 1; // Stop bit 1
    dali_forward_frame[18] = 1; // Stop bit 2
}

// *** GÜNCELLEME 4: create_dali_forward_frame_binary DÜZELTİLDİ ***
// Artık Özel Komutları DOĞRU destekliyor
void create_dali_forward_frame_binary(bool group_or_short, bool directarcpower_or_other, 
                                      uint8_t adress, uint16_t command, 
                                      uint8_t *dali_forward_frame) {

    if (command <= 255) {
        // --- STANDART KOMUT (Mevcut kodunuz - Burası doğru) ---
        
        // Y-Byte (Bit 1-8)
        dali_forward_frame[1] = group_or_short ? 1 : 0;
        
        uint8_t temp_array[8];
        int_to_binary(temp_array, adress, 6); // 'adress' 6 bitlik adres olarak kullanılır
        for (int i = 2; i < 8; i++) {
            dali_forward_frame[i] = temp_array[i - 2];
        }
        
        dali_forward_frame[8] = directarcpower_or_other ? 0 : 1;
                                            
        // X-Byte (Bit 9-16)
        uint8_t temp_array2[8];
        int_to_binary(temp_array2, (uint8_t)command, 8); // 'command' 8 bitlik opcode olarak kullanılır
        for (int i = 9; i < 17; i++) {
            dali_forward_frame[i] = temp_array2[i - 9];
        }

    } else {
        // --- ÖZEL KOMUT (DÜZELTİLMİŞ Yeni Mantık) ---
        // Komut 256'dan büyükse
        
        uint8_t y_byte_opcode = 0;
        
        // Gelen komut numarasına (256-287) göre Y-Byte'ı (Opcode) DALI standardına göre ata
        
        // !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        // !!! DÜZELTME: Y-Byte opcode'ları DALI standardına (sağladığınız tablo) göre düzeltildi.
        // !!! Örn: 256 (TERMINATE) = 0xA1 (1010 0001)
        // !!! Örn: 267 (PROGRAM SHORT) = 0xB7 (1011 0111)
        // !!! Örn: 272 (ENABLE DEVICE) = 0xC1 (1100 0001)
        // !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        switch(command) {
            // 1010 XXX1 (0xA_) Serisi
            case 256: y_byte_opcode = 0xA1; break; // TERMINATE
            case 257: y_byte_opcode = 0xA3; break; // DATA TRANSFER REGISTER (DTR)
            case 258: y_byte_opcode = 0xA5; break; // INITIALISE
            case 259: y_byte_opcode = 0xA7; break; // RANDOMISE
            case 260: y_byte_opcode = 0xA9; break; // COMPARE
            case 261: y_byte_opcode = 0xAB; break; // WITHDRAW
            case 262: y_byte_opcode = 0xAD; break; // RESERVED
            case 263: y_byte_opcode = 0xAF; break; // RESERVED

            // 1011 XXX1 (0xB_) Serisi
            case 264: y_byte_opcode = 0xB1; break; // SEARCHADDRH
            case 265: y_byte_opcode = 0xB3; break; // SEARCHADDRM
            case 266: y_byte_opcode = 0xB5; break; // SEARCHADDRL
            case 267: y_byte_opcode = 0xB7; break; // PROGRAM SHORT ADDRESS
            case 268: y_byte_opcode = 0xB9; break; // VERIFY SHORT ADDRESS
            case 269: y_byte_opcode = 0xBB; break; // QUERY SHORT ADDRESS
            case 270: y_byte_opcode = 0xBD; break; // PHYSICAL SELECTION
            case 271: y_byte_opcode = 0xBF; break; // RESERVED

            // 110C CCC1 (0xC_) Serisi
            case 272: y_byte_opcode = 0xC1; break; // ENABLE DEVICE TYPE X
            // ... 273-287 arası diğer 0xC_ ve 0xD_ serisi komutları buraya eklenebilir
            // ...
            
            default:
                // Bilinmeyen bir özel komut gelirse (örn: 280),
                // güvenli olması için TERMINATE (0xA1) gönder
                y_byte_opcode = 0xA1; 
                Serial.println("[HATA] Bilinmeyen özel komut! TERMINATE (0xA1) gönderiliyor.");
                break;
        }

        // Y-Byte (Bit 1-8)
        // Y-Byte'ı (Opcode) 8 bit olarak yazar
        uint8_t temp_array_y[8];
        int_to_binary(temp_array_y, y_byte_opcode, 8);
        for (int i = 0; i < 8; i++) {
            dali_forward_frame[i+1] = temp_array_y[i];
        }

        // X-Byte (Bit 9-16)
        // 'adress' değişkenini 8 bitlik VERİ (DATA) olarak kullan
        uint8_t temp_array_x[8];
        int_to_binary(temp_array_x, adress, 8); 
        for (int i = 0; i < 8; i++) {
            dali_forward_frame[i+9] = temp_array_x[i];
        }
    }
}


int int_to_binary(uint8_t *array, uint8_t message, uint8_t bit_count) {
    for (int i = 0; i < bit_count; i++) {
        array[i] = (message >> (bit_count - 1 - i)) & 0x01;
    }
    return 0;
}

int binary_to_manchester(uint8_t *binary_message,uint8_t *manchester_message){
    int j = 0;
    for(int i = 0; i < 19; i++){ 
        if(binary_message[i] == 0){
            // Sizin Mantığınız (Ters Manchester): 0 -> 01
            // DALI Standardı (IEC 62386-101): 0 -> 10
            manchester_message[j++] = 0;
            manchester_message[j++] = 1;
        }
        else if(binary_message[i] == 1){ 
            // Sizin Mantığınız (Ters Manchester): 1 -> 10
            // DALI Standardı (IEC 62386-101): 1 -> 01
            manchester_message[j++] = 1;
            manchester_message[j++] = 0;
        }
        else {
            return -1;
        }
    }
    return 0;
}