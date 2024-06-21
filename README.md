## to update liqi_pb2.py:
open the game with developer tool, you can see a traffic: https://mahjongsoul.game.yo-star.com/v0.11.44.w/res/proto/liqi.json
npm install -g protobufjs
pbjs -t proto3 liqi.json > liqi.proto
protoc --python_out=. liqi.proto