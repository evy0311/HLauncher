"""AES-128-CBC/PKCS7 receive decoding through the existing OpenSSL runtime.

Use EVP rather than implementing AES or adding packages to protected root.
"""
import ctypes as c
import ctypes.util
from functools import lru_cache


@lru_cache(maxsize=1)
def backend():
    name = ctypes.util.find_library('crypto')
    if not name:raise ValueError('OpenSSL libcrypto is unavailable')
    lib = c.CDLL(name)
    signatures = {
        'EVP_CIPHER_CTX_new': ([], c.c_void_p),
        'EVP_CIPHER_CTX_free': ([c.c_void_p], None),
        'EVP_aes_128_cbc': ([], c.c_void_p),
        'EVP_DecryptInit_ex': ([c.c_void_p]*5, c.c_int),
        'EVP_DecryptUpdate': ([c.c_void_p,c.c_void_p,c.POINTER(c.c_int),c.c_void_p,c.c_int],c.c_int),
        'EVP_DecryptFinal_ex': ([c.c_void_p,c.c_void_p,c.POINTER(c.c_int)],c.c_int),
    }
    for name,(args,result) in signatures.items():
        function=getattr(lib,name);function.argtypes=args;function.restype=result
    return lib


def decrypt(ciphertext, key):
    if len(key)!=16 or not ciphertext or len(ciphertext)%16 or len(ciphertext)>65536:
        raise ValueError('Invalid encrypted CAN body or key length')
    try:lib=backend()
    except (OSError,AttributeError) as exc:raise ValueError('OpenSSL AES backend unavailable') from exc
    ctx=lib.EVP_CIPHER_CTX_new()
    if not ctx:raise ValueError('Cannot allocate CAN decryptor')
    try:
        key_buffer=c.create_string_buffer(key)
        iv=c.create_string_buffer(bytes(16))
        source=c.create_string_buffer(ciphertext)
        output=c.create_string_buffer(len(ciphertext)+16)
        size=c.c_int();tail=c.c_int()
        if lib.EVP_DecryptInit_ex(ctx,lib.EVP_aes_128_cbc(),None,key_buffer,iv)!=1:
            raise ValueError('Cannot initialize CAN decryptor')
        if lib.EVP_DecryptUpdate(ctx,output,c.byref(size),source,len(ciphertext))!=1:
            raise ValueError('CAN decryption failed')
        if not 0<=size.value<=len(ciphertext):raise ValueError('Invalid CAN decryptor output size')
        if lib.EVP_DecryptFinal_ex(ctx,c.byref(output,size.value),c.byref(tail))!=1:
            raise ValueError('CAN decryption failed: session identity/seed or padding mismatch')
        return output.raw[:size.value+tail.value]
    finally:lib.EVP_CIPHER_CTX_free(ctx)
