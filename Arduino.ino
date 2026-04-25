#include <Servo.h>
#include <LedControl.h>

// ============================================================
// PIN MAP
// ============================================================
const int MATRIX_DIN = 11;
const int MATRIX_CLK = 13;
const int MATRIX_CS  = 12;

// MAIN SERVOS
const int S1_PIN = 26;   // Base
const int S2_PIN = 27;   // Link 1
const int S3_PIN = 32;   // Link 2
const int S4_PIN = 29;   // Link 3
const int S5_PIN = 30;   // Wrist

// EXTRA SERVO
const int S6_PIN = 31;   // Gripper Tool

// RELAYS
const int MAGNET_PIN   = 4;
const int SOLENOID_PIN = 2;
const int VACUUM_PIN   = 3;

// ============================================================
LedControl lc = LedControl(MATRIX_DIN, MATRIX_CLK, MATRIX_CS, 1);

// SERVOS
Servo s1, s2, s3, s4, s5, s6;

// Main arm pose
int currentPos[5] = {90, 90, 90, 90, 90};
int targetPos[5]  = {90, 90, 90, 90, 90};

// Main arm limits
const int MIN_SERVO[5] = {0, 20, 10, 0, 0};
const int MAX_SERVO[5] = {180, 160, 170, 180, 180};

// Gripper tool servo limits
int gripperToolCurrent = 90;
int gripperToolTarget  = 90;
const int GRIPPER_TOOL_MIN = 35;
const int GRIPPER_TOOL_MAX = 95;

// Motion timing
const float STEP_SIZE = 1.0;
const unsigned long STEP_DT = 45;
unsigned long lastStepTime = 0;

// ============================================================
// SERIAL
// ============================================================
String serialBuffer = "";

// ============================================================
// RELAY STATES
// ============================================================
bool magnetState = false;
bool solenoidState = false;
bool vacuumState = false;

// ============================================================
// IDLE ANIMATION
// ============================================================
bool idleAnimEnabled = true;
unsigned long idleLastStep = 0;
const unsigned long IDLE_STEP_MS = 80;
byte idleFrame[8] = {0,0,0,0,0,0,0,0};

// ============================================================
// SIMPLE LETTERS FOR DISPLAY COMMANDS
// ============================================================
byte letterA[8] = {
  B00011000,
  B00100100,
  B01000010,
  B01000010,
  B01111110,
  B01000010,
  B01000010,
  B01000010
};

byte letterB[8] = {
  B01111100,
  B01000010,
  B01000010,
  B01111100,
  B01000010,
  B01000010,
  B01000010,
  B01111100
};

byte letterC[8] = {
  B00111100,
  B01000010,
  B01000000,
  B01000000,
  B01000000,
  B01000000,
  B01000010,
  B00111100
};

// ============================================================
// SERVO HELPERS
// ============================================================
void writeAllServos() {
  s1.write(currentPos[0]);
  s2.write(currentPos[1]);
  s3.write(currentPos[2]);
  s4.write(currentPos[3]);
  s5.write(currentPos[4]);
}

void writeGripperTool() {
  s6.write(gripperToolCurrent);
}

int clampServo(int idx, int val) {
  if (val < MIN_SERVO[idx]) val = MIN_SERVO[idx];
  if (val > MAX_SERVO[idx]) val = MAX_SERVO[idx];
  return val;
}

int clampGripperTool(int val) {
  if (val < GRIPPER_TOOL_MIN) val = GRIPPER_TOOL_MIN;
  if (val > GRIPPER_TOOL_MAX) val = GRIPPER_TOOL_MAX;
  return val;
}

// ============================================================
// DISPLAY HELPERS
// ============================================================
byte reverseByte(byte b) {
  b = (b & 0xF0) >> 4 | (b & 0x0F) << 4;
  b = (b & 0xCC) >> 2 | (b & 0x33) << 2;
  b = (b & 0xAA) >> 1 | (b & 0x55) << 1;
  return b;
}

void drawImageFlipped(const byte img[8]) {
  for (int row = 0; row < 8; row++) {
    lc.setRow(0, row, reverseByte(img[7 - row]));
  }
}

void drawFrameFlipped(const byte frame[8]) {
  for (int row = 0; row < 8; row++) {
    lc.setRow(0, row, reverseByte(frame[7 - row]));
  }
}

void idleAnimReset() {
  for (int i = 0; i < 8; i++) idleFrame[i] = 0x00;
  idleLastStep = millis();
  drawFrameFlipped(idleFrame);
}

void idleAnimUpdate() {
  if (!idleAnimEnabled) return;
  if (millis() - idleLastStep < IDLE_STEP_MS) return;
  idleLastStep = millis();

  for (int r = 0; r < 8; r++) idleFrame[r] <<= 1;
  drawFrameFlipped(idleFrame);
}

void displayText(String txt) {
  txt.trim();
  txt.toUpperCase();

  if (txt == "A") {
    idleAnimEnabled = false;
    drawImageFlipped(letterA);
    return;
  }

  if (txt == "B") {
    idleAnimEnabled = false;
    drawImageFlipped(letterB);
    return;
  }

  if (txt == "C") {
    idleAnimEnabled = false;
    drawImageFlipped(letterC);
    return;
  }

  if (txt == ":)" || txt == "SMILE" || txt == "IDLE") {
    idleAnimEnabled = true;
    idleAnimReset();
    return;
  }

  idleAnimEnabled = true;
  idleAnimReset();
}

// ============================================================
// RELAYS
// ============================================================
void applyRelayStates() {
  digitalWrite(MAGNET_PIN,   magnetState   ? HIGH : LOW);
  digitalWrite(SOLENOID_PIN, solenoidState ? HIGH : LOW);
  digitalWrite(VACUUM_PIN,   vacuumState   ? HIGH : LOW);
}

// ============================================================
// SERIAL PARSING
// Supports:
//   DISPLAY:A
//   90,120,80,90,100
//   TESTSERVO:90
//   MAGNET:ON / MAGNET:OFF
//   SOLENOID:ON / SOLENOID:OFF
//   VACUUM:ON / VACUUM:OFF
// ============================================================
void parseServoLine(String data) {
  int c1 = data.indexOf(',');
  int c2 = data.indexOf(',', c1 + 1);
  int c3 = data.indexOf(',', c2 + 1);
  int c4 = data.indexOf(',', c3 + 1);

  if (c1 > 0 && c2 > 0 && c3 > 0 && c4 > 0) {
    targetPos[0] = clampServo(0, data.substring(0,      c1).toInt());
    targetPos[1] = clampServo(1, data.substring(c1 + 1, c2).toInt());
    targetPos[2] = clampServo(2, data.substring(c2 + 1, c3).toInt());
    targetPos[3] = clampServo(3, data.substring(c3 + 1, c4).toInt());
    targetPos[4] = clampServo(4, data.substring(c4 + 1).toInt());
  }
}

void handleCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();

  if (cmd.startsWith("DISPLAY:")) {
    displayText(cmd.substring(8));
    return;
  }

  if (cmd.startsWith("TESTSERVO:")) {
    int val = cmd.substring(10).toInt();
    gripperToolTarget = clampGripperTool(val);
    return;
  }

  if (cmd == "MAGNET:ON")    { magnetState = true;  applyRelayStates(); return; }
  if (cmd == "MAGNET:OFF")   { magnetState = false; applyRelayStates(); return; }
  if (cmd == "SOLENOID:ON")  { solenoidState = true;  applyRelayStates(); return; }
  if (cmd == "SOLENOID:OFF") { solenoidState = false; applyRelayStates(); return; }
  if (cmd == "VACUUM:ON")    { vacuumState = true;  applyRelayStates(); return; }
  if (cmd == "VACUUM:OFF")   { vacuumState = false; applyRelayStates(); return; }

  parseServoLine(cmd);
}

void handleSerial() {
  while (Serial.available()) {
    char ch = (char)Serial.read();

    if (ch == '\n' || ch == '\r') {
      if (serialBuffer.length() > 0) {
        handleCommand(serialBuffer);
        serialBuffer = "";
      }
    } else {
      serialBuffer += ch;
      if (serialBuffer.length() > 80) {
        serialBuffer = "";
      }
    }
  }
}

// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);

  lc.shutdown(0, false);
  lc.setIntensity(0, 8);
  lc.clearDisplay(0);
  idleAnimReset();

  // Startup at 90
  s1.attach(S1_PIN); s1.write(90);
  s2.attach(S2_PIN); s2.write(90);
  s3.attach(S3_PIN); s3.write(90);
  s4.attach(S4_PIN); s4.write(90);
  s5.attach(S5_PIN); s5.write(90);
  s6.attach(S6_PIN); s6.write(90);

  delay(1000);

  pinMode(MAGNET_PIN, OUTPUT);
  pinMode(SOLENOID_PIN, OUTPUT);
  pinMode(VACUUM_PIN, OUTPUT);

  magnetState = false;
  solenoidState = false;
  vacuumState = false;
  applyRelayStates();

  writeAllServos();
  writeGripperTool();
}

// ============================================================
// LOOP
// ============================================================
void loop() {
  idleAnimUpdate();
  handleSerial();

  if (millis() - lastStepTime >= STEP_DT) {
    lastStepTime = millis();

    bool updatedMain = false;
    bool updatedTool = false;

    for (int i = 0; i < 5; i++) {
      if (currentPos[i] < targetPos[i]) {
        currentPos[i] += STEP_SIZE;
        if (currentPos[i] > targetPos[i]) currentPos[i] = targetPos[i];
        updatedMain = true;
      }
      else if (currentPos[i] > targetPos[i]) {
        currentPos[i] -= STEP_SIZE;
        if (currentPos[i] < targetPos[i]) currentPos[i] = targetPos[i];
        updatedMain = true;
      }
    }

    if (gripperToolCurrent < gripperToolTarget) {
      gripperToolCurrent += STEP_SIZE;
      if (gripperToolCurrent > gripperToolTarget) gripperToolCurrent = gripperToolTarget;
      updatedTool = true;
    }
    else if (gripperToolCurrent > gripperToolTarget) {
      gripperToolCurrent -= STEP_SIZE;
      if (gripperToolCurrent < gripperToolTarget) gripperToolCurrent = gripperToolTarget;
      updatedTool = true;
    }

    if (updatedMain) {
      writeAllServos();
    }

    if (updatedTool) {
      writeGripperTool();
    }
  }
}
