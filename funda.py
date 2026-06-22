def add(x, y): return x + y
def subtract(x, y): return x - y
def multiply(x, y): return x * y
def divide(x, y): return x / y if y != 0 else "Error! Division by zero."

while True:
    print("\n1.Add, 2.Sub, 3.Mul, 4.Div, 5.Exit")
    choice = input("Enter choice (1-5): ")
    if choice == '5': break
    if choice in ('1', '2', '3', '4'):
        try:
            n1 = float(input("Num 1: ")); n2 = float(input("Num 2: "))
            ops = {'1': add, '2': subtract, '3': multiply, '4': divide}
            print("Result:", ops[choice](n1, n2))
        except ValueError: print("Invalid input.")
