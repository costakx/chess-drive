
import chess
import chess.pgn


# ============================================================
# BINARY CONVERSION
# ============================================================

def bytes_to_bits(data):
    return "".join(format(byte, "08b") for byte in data)


def bits_to_bytes(bits):
    if len(bits) % 8 != 0:
        raise ValueError("Recovered data is not byte-aligned")

    return bytes(
        int(bits[i:i + 8], 2)
        for i in range(0, len(bits), 8)
    )


# ============================================================
# METADATA
# 15 bits: game number
# 1 bit: EOF flag
# ============================================================

def encode_metadata(game_number, is_final):
    if not 0 <= game_number < 2**15:
        raise ValueError("Game number must fit in 15 bits")

    bitstream = format(game_number, "015b")
    bitstream += "1" if is_final else "0"

    board = chess.Board()
    encoded_moves = []

    for i, bit in enumerate(bitstream):
        file_index = i // 2

        if i % 2 == 0:
            from_square = chess.square(file_index, 1)
        else:
            from_square = chess.square(file_index, 6)

        distance = 1 if bit == "0" else 2

        to_square = from_square + (
            distance * 8 if i % 2 == 0 else -distance * 8
        )

        move = chess.Move(from_square, to_square)

        if move not in board.legal_moves:
            raise ValueError(f"Illegal metadata move: {move}")

        encoded_moves.append(move.uci())
        board.push(move)

    return encoded_moves


def decode_metadata(encoded_moves):
    if len(encoded_moves) != 16:
        raise ValueError("Metadata must contain exactly 16 moves")

    board = chess.Board()
    decoded_bits = []

    for i, uci in enumerate(encoded_moves):
        move = chess.Move.from_uci(uci)

        if move not in board.legal_moves:
            raise ValueError(f"Illegal metadata move: {uci}")

        expected_file = i // 2
        expected_rank = 1 if i % 2 == 0 else 6

        expected_from = chess.square(expected_file, expected_rank)

        if move.from_square != expected_from:
            raise ValueError(f"Unexpected metadata pawn: {uci}")

        distance = abs(
            chess.square_rank(move.to_square)
            - chess.square_rank(move.from_square)
        )

        if distance not in (1, 2):
            raise ValueError(f"Invalid pawn displacement: {uci}")

        decoded_bits.append("0" if distance == 1 else "1")
        board.push(move)

    bitstream = "".join(decoded_bits)

    game_number = int(bitstream[:15], 2)
    is_final = bitstream[15] == "1"

    return game_number, is_final


def create_payload_board(game_number, is_final):
    board = chess.Board()

    for uci in encode_metadata(game_number, is_final):
        board.push_uci(uci)

    return board


# ============================================================
# PAYLOAD MOVE GENERATION
# ============================================================

def get_payload_moves(board):
    moves = []

    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)

        if piece.piece_type != chess.PAWN:
            moves.append(move)

    return sorted(moves, key=lambda move: move.uci())


def get_capacity(move_count):
    if move_count <= 1:
        return 0

    return move_count.bit_length() - 1


# ============================================================
# PAYLOAD ENCODING
# ============================================================

def encode_final_payload(board, bits):
    encoded_moves = []
    position = 0

    while position < len(bits):
        possible = get_payload_moves(board)
        capacity = get_capacity(len(possible))

        if capacity == 0:
            return encoded_moves, False

        remaining = bits[position:]

        block = remaining[:capacity].ljust(capacity, "0")
        move_index = int(block, 2)

        move = possible[move_index]

        encoded_moves.append(move)
        board.push(move)

        position += min(len(remaining), capacity)

        if len(remaining) <= capacity:
            return encoded_moves, True

    return encoded_moves, True


def encode_nonfinal_payload(board, bits):
    encoded_moves = []
    position = 0

    while position < len(bits):
        possible = get_payload_moves(board)
        capacity = get_capacity(len(possible))

        if capacity == 0:
            break

        remaining = len(bits) - position

        # Non-final games never use partial blocks.
        if remaining < capacity:
            break

        block = bits[position:position + capacity]
        move_index = int(block, 2)

        move = possible[move_index]

        encoded_moves.append(move)
        board.push(move)

        position += capacity

    return encoded_moves, position


# ============================================================
# BUILD A PGN GAME
# ============================================================

def build_game(game_number, is_final, payload_moves):
    game = chess.pgn.Game()

    game.headers["Event"] = "ChessDrive Multi-Game Test"
    game.headers["Round"] = str(game_number + 1)

    node = game

    for uci in encode_metadata(game_number, is_final):
        node = node.add_variation(chess.Move.from_uci(uci))

    for move in payload_moves:
        node = node.add_variation(move)

    return game


# ============================================================
# COMPLETE FILE ENCODER
# ============================================================

def encode_file(data):
    data_bits = bytes_to_bits(data)

    # One sentinel for the entire file.
    data_bits += "1"

    games = []
    position = 0
    game_number = 0

    while True:
        if game_number >= 2**15:
            raise ValueError("Exceeded maximum supported game count")

        remaining_bits = data_bits[position:]

        # First check whether this can be the final game.
        final_board = create_payload_board(game_number, True)

        final_moves, complete = encode_final_payload(
            final_board,
            remaining_bits
        )

        if complete:
            games.append(
                build_game(game_number, True, final_moves)
            )
            break

        # Otherwise encode a non-final game.
        normal_board = create_payload_board(game_number, False)

        normal_moves, consumed = encode_nonfinal_payload(
            normal_board,
            remaining_bits
        )

        if consumed == 0:
            raise ValueError(
                "Non-final game could not encode any complete blocks"
            )

        games.append(
            build_game(game_number, False, normal_moves)
        )

        position += consumed
        game_number += 1

    return games


# ============================================================
# PGN FILE OPERATIONS
# ============================================================

def write_pgn(path, games):
    with open(path, "w", encoding="utf-8") as f:
        for game in games:
            exporter = chess.pgn.FileExporter(f)
            game.accept(exporter)
            f.write("\n")


def read_pgn(path):
    games = []

    with open(path, encoding="utf-8") as f:
        while True:
            game = chess.pgn.read_game(f)

            if game is None:
                break

            games.append(game)

    return games


# ============================================================
# COMPLETE FILE DECODER
# ============================================================

def decode_games(games):
    decoded_games = []

    for game in games:
        moves = list(game.mainline_moves())

        if len(moves) < 16:
            raise ValueError("Game is missing metadata moves")

        metadata = [move.uci() for move in moves[:16]]

        game_number, is_final = decode_metadata(metadata)

        decoded_games.append(
            (game_number, is_final, moves[16:])
        )

    # Metadata, not PGN headers, determines game order.
    decoded_games.sort(key=lambda item: item[0])

    decoded_bits = []
    found_final = False

    for expected_number, (game_number, is_final, payload_moves) in enumerate(
        decoded_games
    ):
        if game_number != expected_number:
            raise ValueError(
                f"Expected game {expected_number}, got {game_number}"
            )

        if found_final:
            raise ValueError("Found a game after the EOF game")

        board = create_payload_board(game_number, is_final)

        for move in payload_moves:
            possible = get_payload_moves(board)
            capacity = get_capacity(len(possible))

            if capacity == 0:
                raise ValueError(
                    f"No payload capacity in game {game_number}"
                )

            try:
                move_index = possible.index(move)
            except ValueError:
                raise ValueError(
                    f"Unexpected payload move: {move.uci()}"
                )

            if move_index >= 2**capacity:
                raise ValueError("Payload move index exceeds capacity")

            decoded_bits.append(
                format(move_index, f"0{capacity}b")
            )

            board.push(move)

        if is_final:
            found_final = True

    if not found_final:
        raise ValueError("No final game / EOF marker found")

    bitstream = "".join(decoded_bits)

    # Find the final sentinel. Everything after it is padding.
    sentinel = bitstream.rfind("1")

    if sentinel == -1:
        raise ValueError("Sentinel not found")

    original_bits = bitstream[:sentinel]

    return bits_to_bytes(original_bits)


# ============================================================
# MAIN TEST
# ============================================================

def main():
    original = b"Hello, ChessDrive! This is a multi-game test."

    print("Original:", original)

    # Generate the original multi-game PGN.
    games = encode_file(original)

    print("\nGenerated games:", len(games))

    for game in games:
        moves = list(game.mainline_moves())

        game_number, is_final = decode_metadata(
            [move.uci() for move in moves[:16]]
        )

        print(
            f"Game {game_number}: "
            f"{len(moves)} total plies, "
            f"final={is_final}"
        )

    write_pgn("examples/multigame_test.pgn", games)

    print("\nPGN written to examples/multigame_test.pgn")

    # Verify the original locally generated PGN.
    local_games = read_pgn("examples/multigame_test.pgn")
    local_decoded = decode_games(local_games)

    print("Local round-trip:", local_decoded == original)

    # Now decode the PGN exported from Chess.com.
    print("\n========== CHESS.COM EXPORT TEST ==========")

    exported_games = read_pgn(
        "examples/multigame_exported.pgn"
    )

    print("Exported games found:", len(exported_games))

    exported_decoded = decode_games(exported_games)

    print("Decoded:", exported_decoded)
    print("Round-trip:", exported_decoded == original)


if __name__ == "__main__":
    main()
