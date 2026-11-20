def read_file(path):
        with open(path, 'rb') as f:
            contents = f.read()
        
        return contents
    
def write_file(path, data):
        with open (path, 'wb') as f:
            f.write(data)
            