import os
import subprocess
import sys
import shutil

# --- SOURCE CODE: RECEIVER (PPM / SERVO VERSION - PIN 4) ---
CODE_RECEIVER = r"""
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
"""

# --- REMOTE CODE (UNCHANGED) ---
CODE_REMOTE = r"""
/* POLE SAW REMOTE */
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>

#define BUTTON_PIN          4
#define DEBOUNCE_MS         50

static BLEUUID serviceUUID("4fafc201-1fb5-459e-8fcc-c5c9c33191b4");
static BLEUUID charUUID("beb5483e-36e1-4688-b7f5-ea07361b26a8");

bool doConnect = false;
bool connected = false;
BLERemoteCharacteristic* pRemoteChar;
BLEAdvertisedDevice* myDevice;
bool lastButtonState = HIGH; 

static void notifyCallback(BLERemoteCharacteristic* pBLERemoteCharacteristic, uint8_t* pData, size_t length, bool isNotify) {}

class MyClientCallback : public BLEClientCallbacks {
  void onConnect(BLEClient* pclient) { connected = true; Serial.println("Connected to Saw"); }
  void onDisconnect(BLEClient* pclient) { connected = false; Serial.println("Disconnected"); }
};

bool connectToServer() {
    Serial.print("Connecting to ");
    Serial.println(myDevice->getAddress().toString().c_str());
    BLEClient* pClient  = BLEDevice::createClient();
    pClient->setClientCallbacks(new MyClientCallback());
    pClient->connect(myDevice);
    BLERemoteService* pRemoteService = pClient->getService(serviceUUID);
    if (pRemoteService == nullptr) { Serial.println("Failed: Service not found"); pClient->disconnect(); return false; }
    pRemoteChar = pRemoteService->getCharacteristic(charUUID);
    if (pRemoteChar == nullptr) { Serial.println("Failed: Char not found"); pClient->disconnect(); return false; }
    if(pRemoteChar->canNotify()) pRemoteChar->registerForNotify(notifyCallback);
    connected = true;
    return true;
}

class MyAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    Serial.print("Scan: "); 
    Serial.print(advertisedDevice.getName().c_str());
    Serial.print(" | ");
    
    if (advertisedDevice.haveServiceUUID()) {
        Serial.print("UUID: ");
        Serial.print(advertisedDevice.getServiceUUID().toString().c_str());
        
        if (advertisedDevice.getServiceUUID().equals(serviceUUID)) {
            Serial.println(" <--- MATCH FOUND!");
            BLEDevice::getScan()->stop();
            myDevice = new BLEAdvertisedDevice(advertisedDevice);
            doConnect = true;
        } else {
            Serial.println("");
        }
    } else {
        Serial.println("(No UUID)");
    }
  }
};

void setup() {
  Serial.begin(115200);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.println("Starting Remote...");
  BLEDevice::init("PoleSaw_Remote");
  BLEScan* pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setInterval(1349);
  pBLEScan->setWindow(449);
  pBLEScan->setActiveScan(true);
}

void loop() {
  if (doConnect) {
    if (connectToServer()) Serial.println("Ready to Cut.");
    else Serial.println("Connection Failed.");
    doConnect = false;
  }

  if (connected) {
    bool reading = digitalRead(BUTTON_PIN);
    if (reading != lastButtonState) {
      delay(DEBOUNCE_MS);
      reading = digitalRead(BUTTON_PIN); 
      if (reading != lastButtonState) {
        lastButtonState = reading;
        if (reading == LOW) { Serial.println("ON"); pRemoteChar->writeValue("1", 1); } 
        else { Serial.println("OFF"); pRemoteChar->writeValue("0", 1); }
      }
    }
  } else {
    BLEDevice::getScan()->start(1, false);
  }
  delay(10);
}
"""

# --- HELPER FUNCTIONS ---

def create_project(name, code, requires_ppm_lib=False):
    base_dir = os.path.join(os.getcwd(), "temp_projects", name)
    src_dir = os.path.join(base_dir, "src")
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)
    os.makedirs(src_dir)

    with open(os.path.join(src_dir, "main.cpp"), "w", encoding="utf-8") as f:
        f.write(code)

    # Added ESP32Servo to lib_deps for Receiver
    libs = "madhephaestus/ESP32Servo" if requires_ppm_lib else ""

    ini_content = f"""
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
upload_speed = 921600
lib_deps =
    {libs}
"""
    with open(os.path.join(base_dir, "platformio.ini"), "w", encoding="utf-8") as f:
        f.write(ini_content)

    return base_dir

def run_pio_command(project_dir, command):
    print(f"\n---> Running: pio {command} in {project_dir}")
    try:
        subprocess.run(["pio"] + command.split(" "), cwd=project_dir, check=True, shell=True)
        return True
    except subprocess.CalledProcessError:
        print("\n[ERROR] Command failed.")
        return False

# --- MAIN MENU ---

def main():
    print("=========================================")
    print("   POLE SAW FLASHER (PPM/SERVO MODE)")
    print("=========================================")
    print("1. Flash RECEIVER (Connects to S/5V/-)")
    print("2. Flash REMOTE (Connects to Button)")
    print("3. Exit")
    
    choice = input("\nEnter choice (1-3): ")

    if choice == "1":
        print("\nPreparing RECEIVER Firmware (PPM Mode on Pin 4)...")
        project_dir = create_project("PoleSaw_Receiver", CODE_RECEIVER, True)
        
        print("Compiling and Flashing... (Connect Receiver ESP32)")
        if run_pio_command(project_dir, "run -t upload"):
            print("\n[SUCCESS] Receiver Flashed Successfully.")
            print("Opening Serial Monitor (Ctrl+C to exit)...")
            run_pio_command(project_dir, "device monitor")

    elif choice == "2":
        print("\nPreparing REMOTE Firmware...")
        project_dir = create_project("PoleSaw_Remote", CODE_REMOTE, False)
        
        print("Compiling and Flashing... (Connect Remote ESP32)")
        if run_pio_command(project_dir, "run -t upload"):
            print("\n[SUCCESS] Remote Flashed Successfully.")
            print("Opening Serial Monitor (Ctrl+C to exit)...")
            run_pio_command(project_dir, "device monitor")

    elif choice == "3":
        sys.exit()

    else:
        print("Invalid Choice.")
        main()

if __name__ == "__main__":
    main()