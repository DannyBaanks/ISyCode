import socket,sys,atexit
attempts=[]
original_connect=socket.socket.connect
original_connect_ex=socket.socket.connect_ex
def deny_connect(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        attempts.append(repr(address))
        raise RuntimeError('historical replay disables internet socket connections')
    return original_connect(self,address)
def deny_connect_ex(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        attempts.append(repr(address))
        raise RuntimeError('historical replay disables internet socket connections')
    return original_connect_ex(self,address)
socket.socket.connect=deny_connect
socket.socket.connect_ex=deny_connect_ex
atexit.register(lambda: print('INTERNET_CONNECTION_ATTEMPTS_BLOCKED:',len(attempts)))
import isycode,textual,pytest
print('SOURCE_PACKAGE:',isycode.__file__)
print('TEXTUAL_VERSION:',textual.__version__)
raise SystemExit(pytest.main(sys.argv[1:]))
