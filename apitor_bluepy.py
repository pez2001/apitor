#!/usr/bin/python3

import sys
import struct
from time import sleep
from binascii import hexlify,unhexlify
import threading

import lupa
from lupa import LuaRuntime

from bluepy import btle

nordic_uart_service_uuid = btle.UUID('6e400001-b5a3-f393-e0a9-e50e24dcca9e')
nordic_uart_tx_uuid = btle.UUID('6e400002-b5a3-f393-e0a9-e50e24dcca9e') #(tx on bot side notify gives replies)
nordic_uart_rx_uuid = btle.UUID('6e400003-b5a3-f393-e0a9-e50e24dcca9e')

apitor_led_colors={0:"Off",1:"Red",2:"Orange",3:"Yellow",4:"Green",5:"Cyan",6:"Blue",7:"Violett",8:"Off"}
apitor_motor_directions={-1:"Backwards",0:"Stopped",1:"Forwards"}

apitor_example_script="T = 0\nwhile true do\n  if T == 0 then\n    if (GD(1)) <= 5 then\n      M(1,9,-1)\n      L(0,4)\n            DS(20)\n      MS(0)\n            T = 1\n    end\n  end\n  if T == 1 then\n    if (GD(1)) > 5 then\n      DS(30)\n      M(1,6,1)\n      L(0,1)\n            DS(20)\n      MS(0)\n            T = 0\n    end\n  end\nend\n"

class UartRxDelegate(btle.DefaultDelegate):
    def __init__(self,device):
        btle.DefaultDelegate.__init__(self)
        self.dev=device
      
    def handleNotification(self, cHandle, data):
        self.dev.handle_data(data)

class ApitorMotorState():
    def __init__(self):
        self.speed=0
        #self.direction=0
    def set_speed(self,speed,direction=None):
        self.speed=speed
        if(direction!=None):
            self.speed=self.speed*direction
    def get_speed(self):
        return(self.speed)
    def get_direction(self):
        if(self.speed==0):
            return(0)
        elif(self.speed>0):
            return(1)
        elif(self.speed<0):
            return(-1)

class ApitorLedState():
    def __init__(self):
        self.color=0
    def set_color(self,color):
        self.color=color
    def get_color(self):
        return(self.color)
        #self.=0

class ApitorDistanceSensorState():
    def __init__(self):
        self.distance=0
    def get_distance(self):
        return(self.distance)

class ApitorState():
    def __init__(self):
        self.motors=[ApitorMotorState(),ApitorMotorState()]
        self.leds=[ApitorLedState(),ApitorLedState(),ApitorLedState(),ApitorLedState()]
        self.distance_sensors=[ApitorDistanceSensorState(),ApitorDistanceSensorState()]
        self.battery_level=0
        #self.script_stored=False
        self.mode=0

    def get_battery_level(self):
        return(self.battery_level)

    #def has_script_stored(self):
    #    return(self.script_stored)


class ApitorDevice():
    def __init__(self,bd_addr):
        self.bd_addr=bd_addr
        self.max_retries=3
        self.connected=False
        self.uid=[]
        self._lock=threading.Lock()
        self.state=ApitorState()
        self.notify_thread=None


    def connect(self,bd_addr=None):
        if(bd_addr!=None):
            self.bd_addr=bd_addr
        retries=self.max_retries
        self.connected=False
        self.dev=None
        while(retries>0):
            print("connecting device...")
            try:
                self.dev=btle.Peripheral(self.bd_addr,"random")
            except btle.BTLEDisconnectError as err:
                print("retries left:",retries,"(",str(err),")")
                self.dev=None
                retries-=1
            if(self.dev!=None):
                break
        if(retries>0):
            self.dev.setDelegate(UartRxDelegate(self))
            self.uart_service=self.dev.getServiceByUUID(nordic_uart_service_uuid)
            self.uart_tx=self.uart_service.getCharacteristics(nordic_uart_tx_uuid)[0]
            self.uart_rx=self.uart_service.getCharacteristics(nordic_uart_rx_uuid)[0]
            self.uart_tx_handle=self.uart_tx.getHandle()
            self.uart_rx_handle=self.uart_rx.getHandle()
            self.uart_rx_ccc=None
            for desriptor in self.dev.getDescriptors(self.uart_rx_handle,0xFFFF):  # The handle range should be read from the services 
                if(desriptor.uuid == 0x2902):                   #      but is not done due to a Bluez/BluePy bug :(     
                    #print("rx Client Characteristic Configuration found at handle 0x"+ format(desriptor.handle,"02X"))
                    self.uart_rx_ccc=desriptor.handle
            if(self.uart_rx_ccc!=None):
                self.dev.writeCharacteristic(self.uart_rx_ccc, struct.pack('<bb', 0x01, 0x00))
                #print("Notification is turned on for rx")
                print("device connected.")
                self.connected=True
        else:
            print("device not connected.")

    def get_state(self):
        return(self.state)

    def update_uid(self):
        # cmd in hex = "fffe0104fdfc"
        cmd=[-1, -2, 1, 4, -3, -4]
        self.send_data(struct.pack('<6b',*cmd))

    def update_state(self):
        #dev.writeCharacteristic(uart_tx_handle, unhexlify("fffe09010200050004040404fdfc"))
        #"fffe09010200000000000000fdfc"
        cmd=[-1, -2, 9, 1, 2, self.state.motors[0].get_speed(), self.state.motors[1].get_speed(), 0, self.state.leds[0].get_color(), self.state.leds[1].get_color(), self.state.leds[2].get_color(), self.state.leds[3].get_color(), -3, -4];
        self.send_data(struct.pack('<14b',*cmd))

    def upload_script(self,lua_script):
        #"fffe09020009000000000000fdfc"
        lua_script_len=len(lua_script)
        cmd=[-1, -2, 9, 2, lua_script_len>>8 , lua_script_len&0xFF, 0, 0, 0, 0, 0, 0, -3, -4];
        #self.send_data(struct.pack('<14b',*cmd))
        self.send_data(struct.pack('<4b2B8b',*cmd))
        #sleep(0.1)
        self.send_data(bytes(lua_script,"ascii"))

    def test(self):
        cmd=[-1, -2, 9, 3, 0, 0, 0, 0, 0, 0, 0, 0, -3, -4];
        self.send_data(struct.pack('<14b',*cmd))
        #cmd=[-1, -2, -1, 4, -3, -4]
        #self.send_data(struct.pack('<6b',*cmd))

    def send_data(self,data):
        #with self._lock:        
            #self.dev.writeCharacteristic(self.uart_tx_handle,data,withResponse=True)
            #print("sending data:",data,flush=True)
            self.dev.writeCharacteristic(self.uart_tx_handle,data)
            #print("sending data done",flush=True)

    
    def handle_data(self,data):
        #print("handle data in device class:",hexlify(data)," length:",len(data))
        if(len(data)==11):
            sdata = struct.unpack('11b',data)
            if(sdata[0]==-1 and sdata[1]==-2 and sdata[9]==-3 and sdata[10]==-4):
                #print("frame detected")
                if(sdata[2]==6):
                    self.state.battery_level=data[5]
                    self.state.mode=data[3]
                    self.state.distance_sensors[0].distance=sdata[7]
                    self.state.distance_sensors[1].distance=sdata[8]
                    #print("state update received:",self.state.battery_level,self.state.distance_sensors[0].distance,self.state.distance_sensors[1].distance,self.state.mode)
        elif(len(data)==13):
            sdata = struct.unpack('13b',data)
            if(sdata[0]==-1 and sdata[1]==-2 and sdata[11]==-3 and sdata[12]==-4):
                #print("frame detected")
                if(sdata[2]==8):
                    self.uid=data[3:11]
                    print("uid update received:",hexlify(self.uid))
        else:
            print("handle data in device class:",hexlify(data)," length:",len(data))

    def run_loop(self):
        while True:
            #with self._lock:        
            #    if(self.dev.waitForNotifications(None)):
            #        continue
            #sleep(0.1)
            if(self.dev.waitForNotifications(0.1)):
                self.update_state()
                continue
            #print("Waiting...")

    def run(self):
        self.notify_thread = threading.Thread(target=self.run_loop, args=())
        self.notify_thread.start()
    def stop(self):
        if(self.notify_thread!=None):
            self.notify_thread.stop()
            self.notify_thread=None

apitor_example_script2='''
T = 0
while true do
  if T == 0 then
    if (GD(1)) <= 5 then
      M(1,9,-1)
      L(0,4)
      DS(20)
      MS(0)
      T = 1
    end
  end
  if T == 1 then
    if (GD(1)) > 5 then
      DS(30)
      M(1,6,1)
      L(0,1)
      DS(20)
      MS(0)
      T = 0
    end
  end
end
'''

class ApitorScript():
    def __init__(self,device=None,lua_script=None):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.device=device
        if(lua_script!=None):
            self.lua_script=lua_script
        else:
            self.lua_script=""
        self.lua.globals()["M"]=self.motor_set
        self.lua.globals()["L"]=self.led_set
        self.lua.globals()["GD"]=self.get_distance
        self.lua.globals()["DS"]=self.device_sleep
        self.lua.globals()["MS"]=self.motor_stop
        self.script_thread=None

    def motor_set(self,motor_id,speed,direction):
        print("setting motor from lua:",motor_id,speed,direction,flush=True)
        if(motor_id==0 or motor_id==1):
           self.device.state.motors[0].set_speed(speed,direction)
        if(motor_id==0 or motor_id==2):
           self.device.state.motors[1].set_speed(speed,direction)
        #self.device.update_state()
        #sleep(0.1)
    def motor_stop(self,motor_id):
        print("stopping motor from lua:",motor_id,flush=True)
        if(motor_id==0 or motor_id==1):
           self.device.state.motors[0].set_speed(0,0)
        if(motor_id==0 or motor_id==2):
           self.device.state.motors[1].set_speed(0,0)
        #self.device.update_state()
        #sleep(0.1)
    def led_set(self,led_id,color):
        print("setting led from lua:",led_id,color,flush=True)
        if(led_id==0 or led_id==1):
           self.device.state.leds[0].set_color(color)
        if(led_id==0 or led_id==2):
           self.device.state.leds[1].set_color(color)
        if(led_id==0 or led_id==3):
           self.device.state.leds[2].set_color(color)
        if(led_id==0 or led_id==4):
           self.device.state.leds[3].set_color(color)
        #self.device.update_state()
        #sleep(0.1)
    def get_distance(self,distance_sensor_id):
        #print("getting distance from lua:",distance_sensor_id,self.device.state.distance_sensors[0].get_distance(),self.device.state.distance_sensors[1].get_distance())
        if(distance_sensor_id==1):
            return(self.device.state.distance_sensors[0].get_distance())
        if(distance_sensor_id==2):
            return(self.device.state.distance_sensors[1].get_distance())
        #sleep(0.1)
    def device_sleep(self,ms):
        print("sleeping from lua:",ms/10,flush=True)
        sleep(ms/10)
        print("sleep done",flush=True)
    
    def set_script(self,lua_script):
        self.lua_script=lua_script
    def set_device(self,device):
        self.device=device

    def run_script(self,lua_script=None,apitor_device=None):
        if(lua_script!=None):
            self.lua_script=lua_script
        if(apitor_device!=None):
            self.device=apitor_device
        print("executing lua script")
        ret=self.lua.execute(self.lua_script)
    def run(self,lua_script=None,apitor_device=None):
        self.script_thread = threading.Thread(target=self.run_script, args=(lua_script,apitor_device))
        self.script_thread.start()
    def stop(self):
        if(self.script_thread!=None):
            self.script_thread.stop()
            self.script_thread=None

if(__name__ == '__main__'):
    if(len(sys.argv)>=2):
        bd_addr = sys.argv[1]
    else:
        bd_addr = "F7:B8:99:22:86:B4"

    apitor=ApitorDevice(bd_addr)
    apitor.connect()
    apitor.update_uid()
    #apitor.upload_script("M(2,5,1)\nM(1,5,1)\n")
    #apitor.upload_script("")
    #apitor.set_motor(1,5,0)
    #apitor.state.leds[0].set_color(2)
    #apitor.update_state()
    apitor_script=ApitorScript(apitor,apitor_example_script2)#"T = 1\nL(T,4)")
    apitor.run()
    apitor_script.run()

    #apitor.test()
    #apitor.run_loop()





