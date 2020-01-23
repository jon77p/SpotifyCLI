from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    args = request.args
    code = args.get('code', None)

    print('RECEIVED CODE: {}'.format(code), flush=True)

    return 'Code received, please close'

if __name__ == "__main__":
    app.run(debug=True)
