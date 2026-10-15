"""NTAG 424 DNA encrypted PICCData profile, NXP AN12196 §§3.4.2/3.4.4.

AES-128 CBC with zero IV, seven-byte UID, little-endian 24-bit counter.
The caller supplies the exact mirrored bytes between configured MAC offsets.
"""
import hmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.cmac import CMAC


def cmac(key, message):
    instance = CMAC(algorithms.AES(key))
    instance.update(message)
    return instance.finalize()


def verify_sun(picc_hex, mac_hex, meta_key, file_key, message=b''):
    try:
        encrypted, supplied = bytes.fromhex(picc_hex), bytes.fromhex(mac_hex)
        if len(encrypted) != 16 or len(supplied) != 8 or len(meta_key) != 16 or len(file_key) != 16:
            raise ValueError('Invalid SUN lengths')
        decryptor = Cipher(algorithms.AES(meta_key), modes.CBC(bytes(16))).decryptor()
        plain = decryptor.update(encrypted) + decryptor.finalize()
        if plain[0] != 0xC7:
            raise ValueError('SUN requires UID and counter mirrors with seven-byte UID')
        uid, counter_bytes = plain[1:8], plain[8:11]
        session_key = cmac(file_key, bytes.fromhex('3CC300010080') + uid + counter_bytes)
        expected = cmac(session_key, message)[1::2]
        if not hmac.compare_digest(expected, supplied):
            raise ValueError('SUN authentication failed')
        return uid.hex().upper(), int.from_bytes(counter_bytes, 'little')
    except (ValueError, TypeError) as error:
        raise ValueError('Invalid SUN proof') from error
