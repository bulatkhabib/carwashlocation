import csv

from flask import Flask, request
from flask_cors import CORS
import requests
import re
import math
import json
import pprint

# Чтение данных из файла CSV
with open('info.csv', newline='') as csvfile:
    reader = csv.reader(csvfile, delimiter=';')
    streets = [(row[1], row[2]) for row in reader]

# Ключ API для 2gis
api_key = 'rudngp8012'

# Определение радиуса в метрах
radius = 1000

rich_coordinates = []
coordinates = {}


def get_coordinates_from_query(address):
    global coordinate_from_query
    url = f'https://catalog.api.2gis.com/3.0/items?q="улица {address} Казань"&fields=items.point&key={api_key}'
    response = requests.get(url).json()
    if response['meta'].get('code') == 200:
        point = response['result']['items'][0]['point']
        coordinate_from_query = (point['lat'], point['lon'])
    return coordinate_from_query


def get_road_info(target_coordinates):
    closest_coordinates = None
    min_distance = float("inf")
    for coords in coordinates.keys():
        distance = math.sqrt((coords[0] - target_coordinates[0]) ** 2 + (coords[1] - target_coordinates[1]) ** 2)
        if distance < min_distance:
            closest_coordinates = coords
            min_distance = distance
    return coordinates[closest_coordinates]

def get_coordinates_from_dataset():
    for street in streets:
        url = f'https://catalog.api.2gis.com/3.0/items?q="улица {street[0]} Казань"&fields=items.point&key={api_key}'
        response = requests.get(url).json()
        if response['meta'].get('code') == 200:
            points = response['result']['items'][0]['point']
            coordinates.update({(points['lat'], points['lon']): int(street[1])})
    return coordinates

def check_carwashes(coordinate):

    num_carwashes = 0
    url = f'https://catalog.api.2gis.com/3.0/items?q="автомойка"&point={coordinate[1]}%2C{coordinate[0]}&fields=items.context,items.point&radius={radius}&key={api_key}'

    response = requests.get(url).json()
    carwashes = {}
    total_self_service_type = 0
    has_self_service_type = False
    if response['meta'].get('code') == 200:
        num_carwashes = response['result'].get('total')

        for item in response['result']['items']:
            name = item['name']
            if 'самообслуживания' in name:
                has_self_service_type = True
                total_self_service_type += 1
            if item['context'] != {}:
                stop_factors = item['context']['stop_factors']
            else:
                continue
            price = None

            for c in stop_factors:
               if 'name' in c and re.search('\d+', c['name']):
                    price = re.search('\d+', c['name']).group()
                    carwashes.update({name: price})
                    break
    return (carwashes, num_carwashes, has_self_service_type, total_self_service_type)


def check_places(coordinate):
    # Формирование запроса к API 2GIS
    url_mall = f'https://catalog.api.2gis.com/3.0/items?point={coordinate[1]}%2C{coordinate[0]}&radius=500&q="торговый центр"&key={api_key}'
    response_mall = requests.get(url_mall).json()

    url_cafe = f'https://catalog.api.2gis.com/3.0/items?point={coordinate[1]}%2C{coordinate[0]}&radius=500&q="кафе"&key={api_key}'
    response_cafe = requests.get(url_cafe).json()

    url_car_service = f'https://catalog.api.2gis.com/3.0/items?point={coordinate[1]}%2C{coordinate[0]}&radius=500&q="автосервис"&key={api_key}'
    response_car_service = requests.get(url_car_service).json()

    total = 0
    places = []
    # Проверка наличия мест в ответе
    if response_mall['meta'].get('code') == 200:
        if response_mall['result'].get('total') > 0:
            total += response_mall['result'].get('total')
        for item in response_mall['result']['items']:
            name = item['name']
            places.append(name)

    if response_cafe['meta'].get('code') == 200:
        if response_cafe['result'].get('total') > 0:
            total += response_cafe['result'].get('total')
        for item in response_cafe['result']['items']:
            name = item['name']
            places.append(name)

    if response_car_service['meta'].get('code') == 200:
        if response_car_service['result'].get('total') > 0:
            total += response_car_service['result'].get('total')
        for item in response_car_service['result']['items']:
            name = item['name']
            places.append(name)

    return (places, total)


# Модель системы массового обслуживания
def calculate_profit(lambda_val, price, job_price, carwash_type):
    if carwash_type == "self-service":
        work_time = 24 # кол-во рабочих часов
        time_to_wash = 15 # время на обслуживание 1 автомобиля
    else:
        work_time = 10 # кол-во рабочих часов
        time_to_wash = 60 # время на обслуживание 1 автомобиля

    max_num_boxes = 8

    # Интенсивность нагрузки
    ro = lambda_val / (60 / time_to_wash)

    # map для сохранения результата
    profits = {}
    for num_boxes in range(1, max_num_boxes + 1):
        la = ro / num_boxes

        if carwash_type == "self-service":
            m = num_boxes * 2
        else:
            m = 0

        if ro != num_boxes:
            b = (la / (1 - la)) * (1 - math.pow(la, m))
        else:
            b = m

        # Доля времени когда боксы свободны
        p = 0
        for k in range(0, num_boxes):
            p = p + math.pow(ro, k) / math.factorial(k)

        p0 = math.pow(p + (math.pow(ro, num_boxes) / math.factorial(num_boxes) * b), -1)
        # Доля отказа (процент необслуженных клиентов)
        s = (math.factorial(num_boxes) * math.pow(num_boxes, m))
        p_cancel = (math.pow(ro, num_boxes + m) / s) * p0

        # Проценты обслуженных клиентов
        q = 1 - p_cancel

        # Кол-во обслуженных авто в час
        la_eff = lambda_val * q

        expected_profit = la_eff * price * work_time * 30 - (num_boxes * int(job_price)) - (la_eff * work_time * 35)

        profits[num_boxes] = round(expected_profit, 2)

    return profits


def find_min_key(data):
    global min_value
    min_key = None
    for key in data:
        if (min_key is None):
            min_key = key
            min_value = int(data[key])
        elif min_value >= int(data[key]):
            min_key = key
            min_value = int(data[key])
    return min_value


def find_max_key(data):
    global max_value
    max_key = None
    for key in data:
        if (max_key is None):
            max_key = key
            max_value = int(data[key])
        elif max_value < int(data[key]):
            max_key = key
            max_value = int(data[key])
    return max_value, max_key

def calculate_clients_and_price(road_info, total_places, total_carwashes, carwash_type, has_self_service_type, carwashes):
    start_clients = road_info / 4 / 30 / 24
    price = 0
    if total_places > 0 and total_places < 3:
        start_clients += (start_clients / 100 * 5)
    else:
        if total_places > 2:
            start_clients += (start_clients / 100 * 10)

    if carwash_type == "self-service":
        price = 150
        start_clients = start_clients / 100 * 20
        if has_self_service_type:
            start_clients = start_clients / carwashes[3]
    else:
        start_clients = start_clients / 100 * 30
        if carwashes[0]:
            carwashes_without_self_service = {k:v for k, v in carwashes[0].items() if "самообслуживания" not in k}
            start_clients = start_clients / len(carwashes_without_self_service)
            price = find_min_key(carwashes_without_self_service) - 50
        else:
            price = 400
    return (start_clients, price)

app = Flask(__name__)
CORS(app)
@app.route('/search', methods=['GET'])
def index():
    variable = request.args.get('search')
    job_price = request.args.get('price')
    if job_price is None:
        job_price = 0
    carwash_type = request.args.get('types')
    query_coordinate = get_coordinates_from_query(variable)
    road_info = get_road_info(query_coordinate)
    places = check_places(query_coordinate)
    carwashes = check_carwashes(query_coordinate)
    result = []
    result.append(f"Для выбранного адреса: {variable}, выполнен анализ, по результату которого:")
    result.append(f"Интенсивность потока автомобилей на данном участке: {road_info} автомобилей в сутки")
    result.append(f"Расположенные рядом объекты инфраструктуры: {'; '.join(places[0])}")
    result.append(f"Расположенные рядом автомойки с их ценами: {', '.join([f'{key.capitalize()} - {value}' for key, value in carwashes[0].items()])}")
    clients_and_price = calculate_clients_and_price(road_info, places[1], carwashes[1], carwash_type, carwashes[2], carwashes)
    print(places, carwashes, carwash_type)
    global res
    if carwash_type == "no-preference":
        result.append("Так как у вас нет предпочтений по типу автомойки - мы предложим вам разные варианты")
        res = calculate_profit(clients_and_price[0], clients_and_price[1], job_price, "standard")
        max_res_standard = find_max_key(res)
        result.append(f"Рассчитанная интенсивность потока клиентов в час составит около: {round(clients_and_price[0], 2)}")
        result.append(f"Цена за услуги в среднем: {clients_and_price[1]}")
        result.append(f"1. Стандартная автомойка: {', '.join([f'{key} - {value} р.' for key, value in res.items()])}")
        result.append(f"Оптимальное количество боксов с наибольшей прибылью: кол-во боксов - {max_res_standard[1]}, прибыль - {max_res_standard[0]} р.")
        clients_and_price_for_self_service = calculate_clients_and_price(road_info, places[1], carwashes[1], "self-service", carwashes[2], carwashes)
        print(clients_and_price_for_self_service[0])
        res_for_self_service = calculate_profit(clients_and_price_for_self_service[0], clients_and_price_for_self_service[1], 0, "self-service")
        max_res_self_service = find_max_key(res_for_self_service)
        result.append(f"2. Автомойка самообслуживания: {', '.join([f'{key} - {value} р.' for key, value in res_for_self_service.items()])}")
        result.append(f"Рассчитанная интенсивность потока клиентов в час составит около: {round(clients_and_price_for_self_service[0], 2)}")
        result.append(f"Цена за услуги в среднем: {clients_and_price_for_self_service[1]}")
        result.append(f"Оптимальное количество боксов с наибольшей прибылью: кол-во боксов - {max_res_self_service[1]}, прибыль - {max_res_self_service[0]} р.")
    else:
        default_res = calculate_profit(clients_and_price[0], clients_and_price[1], job_price, carwash_type)
        result.append(f"Рассчитанная интенсивность потока клиентов в час составит около: {round(clients_and_price[0], 2)}")
        result.append(f"Цена за услуги в среднем: {clients_and_price[1]}")
        result.append(f"Рассчитанная прибыль c количеством боксов по вашему запросу: {', '.join([f'{key} - {value}р.' for key, value in default_res.items()])}")
        max_res = find_max_key(default_res)
        result.append(f"Оптимальное количество боксов с наибольшей прибылью: кол-во боксов - {max_res[1]}, прибыль - {max_res[0]} р.")
    output_dict = {"results": result}
    output_json = json.dumps(output_dict)
    return output_json

if __name__ == '__main__':
    get_coordinates_from_dataset()
    app.run(debug=False)
