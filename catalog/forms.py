from django import forms


class VRClubQuizForm(forms.Form):
    name = forms.CharField(label='Имя', max_length=150)
    phone = forms.CharField(label='Телефон', max_length=40)
    email = forms.EmailField(label='Email', required=False)
    club_format = forms.CharField(label='Формат клуба', max_length=120, required=False)
    devices = forms.CharField(label='Устройства', max_length=255, required=False)
    headsets_count = forms.IntegerField(label='Количество шлемов', required=False, min_value=1)
    play_places_count = forms.IntegerField(label='Игровых мест', required=False, min_value=1)
    audience = forms.CharField(label='Аудитория', max_length=255, required=False)
    budget = forms.CharField(label='Бюджет', max_length=120, required=False)
    comment = forms.CharField(label='Комментарий', required=False, widget=forms.Textarea)
    agree_personal_data = forms.BooleanField(label='Согласие на обработку персональных данных', required=True)
