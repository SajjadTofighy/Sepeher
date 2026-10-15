"""QR byte encoding, error correction M, versions 1–6; standard library only.

Reference fixtures use python-qrcode 8.2 (https://github.com/lincolnloop/python-qrcode).
No runtime import of the reference generator is required.
"""

# (block count, total bytes per block, data bytes per block), level M.
BLOCKS = {1: (1, 26, 16), 2: (1, 44, 28), 3: (1, 70, 44),
          4: (2, 50, 32), 5: (2, 67, 43), 6: (4, 43, 27)}


def multiply(a, b):
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        if a & 256:
            a ^= 0x11D
        b >>= 1
    return result


def parity(data, length):
    generator = [1]
    root = 1
    for _ in range(length):
        product = [0] * (len(generator) + 1)
        for index, coefficient in enumerate(generator):
            product[index] ^= coefficient
            product[index + 1] ^= multiply(coefficient, root)
        generator = product
        root = multiply(root, 2)
    remainder = list(data) + [0] * length
    for index in range(len(data)):
        coefficient = remainder[index]
        for offset, value in enumerate(generator):
            remainder[index + offset] ^= multiply(value, coefficient)
    return remainder[-length:]


def codewords(payload, version):
    count, total, capacity = BLOCKS[version]
    bits = '0100' + f'{len(payload):08b}' + ''.join(f'{b:08b}' for b in payload)
    limit = count * capacity * 8
    if len(payload) > 255 or len(bits) > limit:
        raise ValueError('Payload does not fit QR version at level M')
    bits += '0' * min(4, limit - len(bits))
    bits += '0' * ((-len(bits)) % 8)
    data = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    while len(data) < count * capacity:
        data.append(0xEC if (len(data) - len(bits) // 8) % 2 == 0 else 0x11)
    blocks = [data[i * capacity:(i + 1) * capacity] for i in range(count)]
    checks = [parity(block, total - capacity) for block in blocks]
    return [b[i] for i in range(capacity) for b in blocks] + [b[i] for i in range(total - capacity) for b in checks]


def masked(row, col, mask):
    return ((row + col) % 2 == 0, row % 2 == 0, col % 3 == 0,
            (row + col) % 3 == 0, (row // 2 + col // 3) % 2 == 0,
            row * col % 2 + row * col % 3 == 0,
            (row * col % 2 + row * col % 3) % 2 == 0,
            ((row + col) % 2 + row * col % 3) % 2 == 0)[mask]


def matrix(text, version=None, mask=0):
    """Return modules without quiet zone; deterministic mask 0 by default."""
    payload = text.encode('utf-8')
    if version is None:
        version = next((v for v, (count, _, cap) in BLOCKS.items() if 12 + 8 * len(payload) <= count * cap * 8), None)
    if version not in BLOCKS or not isinstance(mask, int) or not 0 <= mask <= 7:
        raise ValueError('Only versions 1–6, masks 0–7 and correction M are supported')
    words = codewords(payload, version)
    size = 17 + version * 4
    modules = [[None] * size for _ in range(size)]
    for x, y in ((0, 0), (size - 7, 0), (0, size - 7)):
        for dy in range(-1, 8):
            for dx in range(-1, 8):
                if 0 <= x + dx < size and 0 <= y + dy < size:
                    modules[y + dy][x + dx] = (0 <= dx <= 6 and 0 <= dy <= 6
                        and (dx in (0, 6) or dy in (0, 6) or (2 <= dx <= 4 and 2 <= dy <= 4)))
    if version > 1:
        center = size - 7
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                modules[center + dy][center + dx] = max(abs(dx), abs(dy)) != 1
    for i in range(8, size - 8):
        modules[6][i] = modules[i][6] = i % 2 == 0
    format_bits = mask << 10  # Error correction M is binary 00.
    for bit in range(14, 9, -1):
        if format_bits & (1 << bit):
            format_bits ^= 0x537 << (bit - 10)
    format_bits = ((mask << 10) | format_bits) ^ 0x5412
    first = [(8, i) for i in range(6)] + [(8, 7), (8, 8), (7, 8)] + [(14 - i, 8) for i in range(9, 15)]
    second = [(size - 1 - i, 8) for i in range(8)] + [(8, size - 15 + i) for i in range(8, 15)]
    for i, (a, b) in enumerate(zip(first, second)):
        for x, y in (a, b):
            modules[y][x] = bool((format_bits >> i) & 1)
    modules[size - 8][8] = True
    bits = ''.join(f'{b:08b}' for b in words)
    index, right, upward = 0, size - 1, True
    while right > 0:
        if right == 6:
            right -= 1
        for row in (range(size - 1, -1, -1) if upward else range(size)):
            for col in (right, right - 1):
                if modules[row][col] is None:
                    value = index < len(bits) and bits[index] == '1'
                    modules[row][col] = value != masked(row, col, mask)
                    index += 1
        upward = not upward
        right -= 2
    return modules


def svg(text):
    modules = matrix(text)
    size = len(modules) + 8  # Four-module quiet zone on all sides.
    path = ''.join(f'M{x + 4},{y + 4}h1v1h-1z' for y, row in enumerate(modules) for x, dark in enumerate(row) if dark)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges"><rect width="100%" height="100%" fill="white"/><path d="{path}" fill="black"/></svg>'
