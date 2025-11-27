from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from django.shortcuts import render 

from .serializers import HL7TransformRequestSerializer
from .hl7_utils import hl7_to_all

# ⬇⬇⬇ add this function-based view
def index(request):
    # if your file is templates/index.html and TEMPLATES.DIRS 已经配置好，
    # 这个名字就是 "index.html"
    return render(request, "index.html")


class HL7TransformView(APIView):
    # 只用 JSONRenderer，不用 BrowsableAPIRenderer
    renderer_classes = [JSONRenderer]

    def post(self, request, *args, **kwargs):
        serializer = HL7TransformRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hl7_message = serializer.validated_data["hl7_message"]
        result = hl7_to_all(hl7_message)
        return Response(result, status=status.HTTP_200_OK)
