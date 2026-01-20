
/* POLE SAW RECEIVER (HYBRID MODE: REMOTE + APP) */
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <ESP32Servo.h> 

// --- PIN CONFIGURATION ---
#define SERVO_PIN           4     // Signal Output on GPIO 4
#define STATUS_LED          2     // Onboard LED for status

#define MAX_THROTTLE        180   // 180 degrees (approx 2000us pulse)
// NOTE: Some ESCs need a wider range or specific calibration. 
// Standard Servo lib is 544us-2400us, but we attach as 1000-2000 below.

#define RAMP_UP_TIME_MS     2000  // <--- UPDATED: 2.0 Seconds Soft Start
#define RAMP_DOWN_TIME_MS   300   // Quick stop time
#define LOOP_RATE_HZ        50

#define SERVICE_UUID        "4fafc201-1fb5-459e-8fcc-c5c9c33191b4"
#define CONTROL_CHAR_UUID   "beb5483e-36e1-4688-b7f5-ea07361b26a8"

Servo vescServo;
BLEServer* pServer = NULL;
BLECharacteristic* pControlChar = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

// Variables for Smoothing
float currentThrottle = 0.0;
float targetThrottle = 0.0;   // <--- NEW: Target we are aiming for
float rampUpStep = 0.0;
float rampDownStep = 0.0;
unsigned long lastLoopTime = 0;
unsigned long lastPacketTime = 0; // For Safety Watchdog

class ServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
        deviceConnected = true;
        digitalWrite(STATUS_LED, HIGH);
        Serial.println("Device Connected");
    };
    void onDisconnect(BLEServer* pServer) {
        deviceConnected = false;
        targetThrottle = 0.0; // Safety Kill
        digitalWrite(STATUS_LED, LOW);
        Serial.println("Device Disconnected");
    }
};

class ControlCallbacks: public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *pCharacteristic) {
        std::string value = pCharacteristic->getValue();
        if (value.length() > 0) {
            uint8_t data = value[0];
            lastPacketTime = millis(); // Reset Watchdog

            // --- HYBRID LOGIC ---
            if (data == '1' || data == 0x31) {
                // Legacy REMOTE "ON" -> Go to 100%
                targetThrottle = MAX_THROTTLE;
                Serial.println("CMD: REMOTE ON");
            } 
            else if (data == '0' || data == 0x30) {
                // Legacy REMOTE "OFF" -> Go to 0%
                targetThrottle = 0;
                Serial.println("CMD: REMOTE OFF");
            }
            else {
                // APP SLIDER (0-255)
                // Map 0-255 to 0-180
                // If data is small (< 5), treat as 0 to avoid noise
                if (data < 5) targetThrottle = 0;
                else targetThrottle = map(data, 0, 255, 0, MAX_THROTTLE);
                
                // Serial.printf("CMD: APP TARGET %f\n", targetThrottle);
            }
        }
    }
};

void setup() {
    Serial.begin(115200);
    pinMode(STATUS_LED, OUTPUT);
    digitalWrite(STATUS_LED, LOW);

    // Setup Servo (PPM) Output on Pin 4
    vescServo.attach(SERVO_PIN, 1000, 2000);
    vescServo.write(0); // Initialize at 0 throttle

    // Calculate Ramp Steps (Amount to change per loop)
    // Code runs at 50Hz (20ms per loop)
    // Steps = Total Change / (Total Time / Loop Time)
    rampUpStep = (float)MAX_THROTTLE / (RAMP_UP_TIME_MS / (1000.0 / LOOP_RATE_HZ));
    rampDownStep = (float)MAX_THROTTLE / (RAMP_DOWN_TIME_MS / (1000.0 / LOOP_RATE_HZ));

    // BLE Setup
    BLEDevice::init("PoleSaw_RX");
    pServer = BLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());
    BLEService *pService = pServer->createService(SERVICE_UUID);
    pControlChar = pService->createCharacteristic(CONTROL_CHAR_UUID, BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_WRITE);
    pControlChar->setCallbacks(new ControlCallbacks());
    pService->start();
    
    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setScanResponse(true);
    pAdvertising->setMinPreferred(0x06);
    BLEDevice::startAdvertising();
    Serial.println("Waiting for Connection...");
}

void loop() {
    // BLE Reconnection Logic
    if (!deviceConnected && oldDeviceConnected) {
        delay(500); 
        pServer->startAdvertising(); 
        oldDeviceConnected = deviceConnected;
    }
    if (deviceConnected && !oldDeviceConnected) {
        oldDeviceConnected = deviceConnected;
    }

    // Safety Watchdog: If connected but no data for 2 seconds, stop?
    // Actually, App might not send data if slider isn't moving. 
    // We will rely on Disconnect event for main safety.
    // But if Connection Hangs? Good practice to auto-zero if silence > 5s.
    if (deviceConnected && (millis() - lastPacketTime > 5000) && targetThrottle > 0) {
        // Optional: Keep alive check needed? 
        // For now, let's trust BLE link supervision timeout.
    }

    // Ramping Logic (50Hz)
    if (millis() - lastLoopTime >= (1000 / LOOP_RATE_HZ)) {
        lastLoopTime = millis();
        
        // Move Current -> Target
        if (currentThrottle < targetThrottle) {
            currentThrottle += rampUpStep;
            if (currentThrottle > targetThrottle) currentThrottle = targetThrottle;
        } 
        else if (currentThrottle > targetThrottle) {
            currentThrottle -= rampDownStep;
            if (currentThrottle < targetThrottle) currentThrottle = targetThrottle;
        }

        // Safety Clamps
        if (currentThrottle < 0) currentThrottle = 0;
        if (currentThrottle > MAX_THROTTLE) currentThrottle = MAX_THROTTLE;

        // Send to VESC
        if (!deviceConnected) {
             targetThrottle = 0; 
             // Force zero immediately if disconnected
             currentThrottle = 0; 
        }
        
        vescServo.write((int)currentThrottle);
    }
}
