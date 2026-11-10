from flask import Flask, render_template, jsonify

app = Flask(__name__)

# Route to serve the HTML page
@app.route('/')
def index():
    return render_template('index.html')

# API Route that JavaScript will fetch data from
@app.route('/api/hello')
def hello_api():
    return jsonify({"message": "Hello World from the Flask backend!"})

if __name__ == '__main__':
    app.run(debug=False)