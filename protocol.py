import header_pb2
import liqi_pb2
from google.protobuf import message_factory

class Message:
    def __init__(self):
        self.type = 'unknown'
        self.seq = -1
        self.name = 'unknown'
        self.data = None

class Protocol:
    def __init__(self):
        self.seq_to_rsp = {}

    def parse_message(self, data):
        ret = Message()
        msg_type = data[0]
        if msg_type == 1: # notify
            ret.type = 'notify'
            header = header_pb2.Header()
            header.ParseFromString(data[1:])
            data_type = self.get_message_type(header.name)
            if data_type:
                ret.name = data_type.DESCRIPTOR.full_name
                ret.data = data_type()
                try:
                    ret.data.ParseFromString(header.data)
                except:
                    ret.data = None
        elif msg_type == 2: # request
            ret.type = 'request'
            ret.seq = data[1] + data[2] * 256
            header = header_pb2.Header()
            header.ParseFromString(data[3:])
            input_type, output_type = self.get_method_types(header.name)
            if input_type and output_type:
                ret.name = input_type.DESCRIPTOR.full_name
                try:
                    ret.data = input_type()
                    ret.data.ParseFromString(header.data)
                except:
                    ret.data = None
                self.seq_to_rsp[ret.seq] = output_type
        elif msg_type == 3: # response
            ret.type = 'response'
            ret.seq = data[1] + data[2] * 256
            header = header_pb2.Header()
            header.ParseFromString(data[3:])
            output_type = self.seq_to_rsp.get(ret.seq, None)
            if output_type:
                self.seq_to_rsp.pop(ret.seq)
                ret.name = output_type.DESCRIPTOR.full_name
                try:
                    ret.data = output_type()
                    ret.data.ParseFromString(header.data)
                except:
                    ret.data = None
        return ret
    
    def get_method_types(self, name: str):
        name_list = name.split('.')
        name_list = [x for x in name_list if x]
        if len(name_list) == 0 or name_list[0] != 'lq':
            return (None, None)
        name_list = name_list[1:]
        if len(name_list) == 0:
            return (None, None)
        method_name = name_list.pop(-1)
        service_name = '.'.join(name_list)
        service = liqi_pb2.DESCRIPTOR.services_by_name.get(service_name, None)
        if not service:
            return (None, None)
        method = service.methods_by_name.get(method_name, None)
        if not method:
            return (None, None)
        return (message_factory.GetMessageClass(method.input_type),
                message_factory.GetMessageClass(method.output_type))
    
    def get_message_type(self, name: str):
        name_list = name.split('.')
        name_list = [x for x in name_list if x]
        if len(name_list) == 0 or name_list[0] != 'lq':
            return None
        name_list = name_list[1:]
        if len(name_list) == 0:
            return None
        message_name = '.'.join(name_list)
        message = liqi_pb2.DESCRIPTOR.message_types_by_name.get(message_name, None)
        if not message:
            return None
        return message_factory.GetMessageClass(message)

PROTOCOL = Protocol()

if __name__ == '__main__':
    data = [
        b'\x01\n\x17.lq.NotifyAccountUpdate\x12\x8d\x01\n\x8a\x01\n\x08\x08\xa2\x8d\x06\x18\xde\xbc\x02"~\n\x0c\x08\xc9\x8f\x06\x10\xde\xbc\x02\x18\x00 \x00\n\x0c\x08\xca\x8f\x06\x10\xde\xbc\x02\x18\x00 \x00\n\x0c\x08\xcb\x8f\x06\x10\xde\xbc\x02\x18\x00 \x00\n\x0c\x08\xcc\x8f\x06\x10\xde\xbc\x02\x18\x00 \x00\n\x0c\x08\xcd\x8f\x06\x10\xce\xee\x01\x18\x00 \x00\n\x0c\x08\xce\x8f\x06\x10\xce\xee\x01\x18\x00 \x00\n\x0c\x08\xcf\x8f\x06\x10\xce\xee\x01\x18\x00 \x00\n\x0c\x08\xd0\x8f\x06\x10\xce\xee\x01\x18\x00 \x00\n\x0c\x08\xd1\x8f\x06\x10\xce\xee\x01\x18\x00 \x00',
        b'\x02\x1f\x00\n\x19.lq.Lobby.fetchServerTime\x12\x00',
        b'\x03\x1f\x00\n\x00\x12\x06\x08\xbd\xdc\xce\xb3\x06',
    ]
    for buf in data:
        msg = PROTOCOL.parse_message(buf)
        print(f"{msg.type}, {msg.seq}, {msg.name}, {msg.data}")
