
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
