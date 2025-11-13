import json
import mysql.connector as sql

input_files = open('ResearchTestLinks.json')
json_decode=json.load(input_files)

database_connection = sql.connect(user = 'root', password = 'Drmfslsd120!', host = '127.0.0.1', database = 'researchdb') #Login

cursor = database_connection.cursor() #Structure to insert or update data according to mysql documentation


for entry in json_decode:
    url = entry['url']
    doi = entry['doi']
    title = entry['title']
    
    # SQL INSERT Request
    sql_insert = "INSERT INTO CLASSIFICATION (title, DOI, DONE) VALUES (%s, %s, %s)"
    cursor.execute(sql_insert, (title, doi, False))
    
    

database_connection.commit()