import uuid

# Automatically generate a 16 byte UUID
dev_uuid = uuid.uuid4()
with open('dev_info', 'w') as file:
    file.write(f'UUID={dev_uuid}\n')

# Ask user to write school name
user_text = input("Write school name:")
with open('dev_info', 'a') as file:
    file.write(f'SCHOOL={user_text}')
